"""
mobile_de_full_scraper.py - High-Performance Detail Scraper for mobile.de with Cloudflare WARP IP Rotation.

Features:
  - Bypasses Akamai Bot Manager using Camoufox (Stealth Firefox)
  - Automatically lets Akamai sensor interstitials solve in 2 seconds (no unnecessary WARP swaps)
  - Automatic Cloudflare WARP IP rotation only on genuine hard-blocks ("Zugriff verweigert")
  - Blazing-fast page loads (~1.0s) via asset route interception (images/media/fonts)
  - Cookie clearing on IP rotation to prevent carryover of flagged Akamai sessions
  - 100% strict schema preservation matching mobile_de_full.jsonl (all 31 canonical keys)
  - Resilient, crash-safe checkpointing that cleanly resumes where it left off
  - Periodic and final export to data/raw/mobile_de_full.csv

Usage:
  py script/mobile_de_full_scraper.py --enrich --target 20000
"""

import argparse
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from camoufox.sync_api import Camoufox
import pandas as pd

# Directories
SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXTRACTION_DIR.parent

for p in [str(EXTRACTION_DIR), str(SCRIPT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

DATA_DIR = REPO_ROOT / "data"
MOBILEDE_DATA_DIR = DATA_DIR / "mobilede"
MOBILEDE_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mobile_de_full")

CANONICAL_KEYS = [
    "title",
    "price",
    "currency",
    "body_type",
    "mileage_km",
    "engine_displacement_cm3",
    "power_kw",
    "power_hp",
    "transmission",
    "fuel_type",
    "first_registration",
    "euro_standard",
    "doors",
    "seats",
    "color",
    "condition",
    "accident_free",
    "damaged",
    "air_conditioning",
    "features",
    "listing_id",
    "listing_url",
    "brand",
    "model",
    "seller_name",
    "seller_city",
    "seller_postal_code",
    "seller_country",
    "price_bracket",
    "source",
    "scraped_at",
]


def rotate_warp_ip() -> bool:
    """Rotate IP via Cloudflare WARP CLI to bypass Akamai rate limits."""
    warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
    if not os.path.exists(warp_cli):
        log.warning(f"Cloudflare WARP CLI not found at: {warp_cli}")
        return False
    try:
        log.info("Detected Akamai block/denied screen. Rotating Cloudflare WARP IP...")
        subprocess.run([warp_cli, "tunnel", "rotate-keys"], capture_output=True, timeout=10)
        subprocess.run([warp_cli, "disconnect"], capture_output=True, timeout=10)
        time.sleep(2)
        subprocess.run([warp_cli, "connect"], capture_output=True, timeout=10)

        # Wait for WARP to establish connection
        connected = False
        for _ in range(8):
            time.sleep(1.5)
            try:
                res = subprocess.run([warp_cli, "status"], capture_output=True, text=True, timeout=5)
                if "Connected" in res.stdout:
                    connected = True
                    break
            except Exception:
                pass

        if not connected:
            log.warning("WARP connection did not report 'Connected' within expected window.")

        try:
            new_ip = subprocess.check_output(
                ["curl.exe", "-s", "--max-time", "5", "https://api.ipify.org"], timeout=6
            ).decode().strip()
            log.info(f"Cloudflare WARP rotated successfully. New IP: {new_ip}")
        except Exception:
            log.info("Cloudflare WARP connected.")
        return True
    except Exception as e:
        log.warning(f"Automatic WARP rotation error: {e}")
        return False


def setup_clean_page(browser):
    """Creates a fresh page, intercepts heavy assets for 3x speed, and dismisses cookie consent."""
    page = browser.new_page()

    # Block heavy assets to maximize scraping speed (~1s per car)
    def intercept_route(route):
        if route.request.resource_type in ["image", "media", "font"]:
            route.abort()
        else:
            route.continue_()

    try:
        page.route("**/*", intercept_route)
    except Exception:
        pass

    try:
        page.goto("https://www.mobile.de", wait_until="domcontentloaded", timeout=25000)
        time.sleep(1.0)
        for sel in [
            'button[data-testid="mde-consent-modal-accept-btn"]',
            'button:has-text("Alle akzeptieren")',
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Zustimmen")',
            'button:has-text("Einverstanden")',
            '#mde-consent-modal-container button',
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    break
            except Exception:
                pass
    except Exception as e:
        log.warning(f"Notice during page initialization: {e}")
    return page


def is_hard_blocked(html: str) -> bool:
    """Detect if page is a real, hard blocked screen (Zugriff verweigert / Access Denied)."""
    lower = html.lower()
    denied_markers = [
        "zugriff verweigert",
        "access denied",
        "403 forbidden",
        "you don't have permission to access",
    ]
    return any(marker in lower for marker in denied_markers)


def build_canonical_record(row, rec: dict | None, is_expired: bool = False) -> dict:
    """Builds a record strictly matching the 31-column schema of mobile_de_full.jsonl."""
    r = rec if rec and rec.get("_status") != "expired" else {}

    def _val(k, default=None):
        v = r.get(k)
        if v is not None:
            return v
        return default

    # Price fallback
    price = _val("price")
    if price is None and pd.notna(row.get("price")):
        try:
            price = float(row.get("price"))
        except Exception:
            price = None

    # Mileage fallback
    mileage = _val("mileage_km")
    if mileage is None and pd.notna(row.get("mileage_km")):
        try:
            mileage = int(float(row.get("mileage_km")))
        except Exception:
            mileage = None

    # Power fallback
    power_kw = _val("power_kw")
    if power_kw is None and pd.notna(row.get("power_kw")):
        try:
            power_kw = int(float(row.get("power_kw")))
        except Exception:
            power_kw = None

    power_hp = _val("power_hp")
    if power_hp is None and pd.notna(row.get("power_hp")):
        try:
            power_hp = int(float(row.get("power_hp")))
        except Exception:
            power_hp = None

    # Accident free fallback
    accident_free = _val("accident_free")
    if accident_free is None and pd.notna(row.get("accident_free")):
        accident_free = bool(row.get("accident_free"))

    # Postal code fallback
    postal_code = None
    if pd.notna(row.get("seller_postal_code")):
        try:
            postal_code = float(row.get("seller_postal_code"))
        except Exception:
            postal_code = None

    return {
        "title": _val("title") or row.get("title"),
        "price": price,
        "currency": "EUR",
        "body_type": _val("body_type"),
        "mileage_km": mileage,
        "engine_displacement_cm3": _val("engine_displacement_cm3"),
        "power_kw": power_kw,
        "power_hp": power_hp,
        "transmission": _val("transmission"),
        "fuel_type": _val("fuel_type") or (row.get("fuel_type") if pd.notna(row.get("fuel_type")) else None),
        "first_registration": _val("first_registration") or (str(row.get("first_registration")) if pd.notna(row.get("first_registration")) else None),
        "euro_standard": _val("euro_standard"),
        "doors": _val("doors"),
        "seats": _val("seats"),
        "color": _val("color"),
        "condition": "expired" if is_expired else (_val("condition") or "Gebrauchtfahrzeug"),
        "accident_free": accident_free,
        "damaged": _val("damaged"),
        "air_conditioning": _val("air_conditioning"),
        "features": _val("features"),
        "listing_id": str(row.get("listing_id")),
        "listing_url": str(row.get("listing_url")),
        "brand": row.get("brand") if pd.notna(row.get("brand")) else None,
        "model": row.get("model") if pd.notna(row.get("model")) else None,
        "seller_name": row.get("seller_name") if pd.notna(row.get("seller_name")) else None,
        "seller_city": row.get("seller_city") if pd.notna(row.get("seller_city")) else None,
        "seller_postal_code": postal_code,
        "seller_country": row.get("seller_country", "DE") if pd.notna(row.get("seller_country")) else "DE",
        "price_bracket": row.get("price_bracket") if pd.notna(row.get("price_bracket")) else "",
        "source": "mobile_de",
        "scraped_at": datetime.now().isoformat(),
    }


class FullCheckpoint:
    """Atomic, crash-safe checkpoint tracker that guarantees clean resume."""

    def __init__(self, filename: str = "mobile_de_full_checkpoint.json"):
        self.filename = filename
        self.path = MOBILEDE_DATA_DIR / filename
        self.data = self._load()

    def _load(self) -> dict:
        default_data = {
            "scraped_ids": [],
            "failed_ids": [],
            "expired_ids": [],
            "bracket_index": 0,
            "last_page": 0,
            "total_scraped": 0,
            "last_updated": None,
            "failed_urls": [],
        }
        candidates = [
            self.path,
            self.path.with_suffix(".tmp"),
            DATA_DIR / "checkpoints" / self.filename,
        ]
        for p in candidates:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        if isinstance(d, dict) and "scraped_ids" in d:
                            d.setdefault("failed_ids", [])
                            d.setdefault("expired_ids", [])
                            d.setdefault("failed_urls", [])
                            return d
                except Exception:
                    pass
        return default_data

    def save(self):
        self.data["last_updated"] = datetime.now().isoformat()
        temp_p = self.path.with_suffix(".tmp")
        try:
            with open(temp_p, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_p, self.path)
        except Exception as e:
            log.warning(f"Error saving checkpoint: {e}")

    @property
    def scraped_ids(self) -> set:
        return set(str(x) for x in self.data.get("scraped_ids", []))

    @property
    def processed_ids(self) -> set:
        """All IDs processed (scraped, failed, or expired) to avoid re-attempt loops on resume."""
        s = set(str(x) for x in self.data.get("scraped_ids", []))
        s.update(str(x) for x in self.data.get("failed_ids", []))
        s.update(str(x) for x in self.data.get("expired_ids", []))
        for u in self.data.get("failed_urls", []):
            m = re.search(r"id=(\d+)", str(u))
            if m:
                s.add(m.group(1))
        return s

    def add_id(self, lid: str):
        lid_str = str(lid)
        if lid_str not in self.scraped_ids:
            self.data["scraped_ids"].append(lid_str)
            self.data["total_scraped"] = len(self.data["scraped_ids"])
            self.save()

    def add_failed(self, lid: str, url: str):
        lid_str = str(lid)
        if "failed_ids" not in self.data:
            self.data["failed_ids"] = []
        if lid_str not in self.data["failed_ids"]:
            self.data["failed_ids"].append(lid_str)
        if url not in self.data["failed_urls"]:
            self.data["failed_urls"].append(url)
        self.save()

    def add_expired(self, lid: str, url: str):
        lid_str = str(lid)
        if "expired_ids" not in self.data:
            self.data["expired_ids"] = []
        if lid_str not in self.data["expired_ids"]:
            self.data["expired_ids"].append(lid_str)
        self.save()


class MobileDeFullScraper:
    """Production scraper extracting complete technical specifications."""

    def __init__(self, target: int = 20000):
        self.target = target
        self.checkpoint = FullCheckpoint()
        self.jsonl_path = MOBILEDE_DATA_DIR / "mobile_de_full.jsonl"
        self._fh = open(self.jsonl_path, "a", encoding="utf-8")

    def _write_record(self, record: dict):
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        try:
            os.fsync(self._fh.fileno())
        except Exception:
            pass

    def parse_detail_html(self, html: str, url: str) -> dict | None:
        """Parse technical attributes from detail page HTML."""
        if is_hard_blocked(html):
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 1. Check ad title
        h1 = soup.select_one("h1#ad-title, h1[data-testid='ad-title'], h1")
        title_text = h1.get_text(strip=True) if h1 else None
        if not title_text or "zugriff verweigert" in title_text.lower() or "access denied" in title_text.lower():
            return None

        # 2. Check for expired/removed vehicle
        page_text = soup.get_text(" ", strip=True).lower()
        if "dieses fahrzeug ist nicht mehr verfügbar" in page_text or "inserat ist nicht mehr verfügbar" in page_text:
            return {"_status": "expired"}

        # 3. Technical specification dictionary
        specs = {}
        for dt in soup.select("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                k = dt.get_text(strip=True).lower()
                v = dd.get_text(strip=True)
                specs[k] = v

        for row in soup.select(".g-row, .cBox--body"):
            cols = row.select("div")
            if len(cols) == 2:
                k = cols[0].get_text(strip=True).lower()
                v = cols[1].get_text(strip=True)
                if k and v and k not in specs:
                    specs[k] = v

        # If no specs found, it is not a valid vehicle page
        if not specs:
            return None

        record = {"title": title_text}

        # Price
        price_el = soup.select_one("[data-testid='prime-price'], .main-price, .vip-title-price")
        if price_el:
            p_text = price_el.get_text(strip=True).replace(".", "").replace(" ", "").replace(",", ".")
            m = re.search(r"(\d+(?:\.\d+)?)", p_text)
            record["price"] = float(m.group(1)) if m else None
            record["currency"] = "EUR"
        else:
            record["price"] = None
            record["currency"] = "EUR"

        # Map specifications
        record["body_type"] = specs.get("kategorie")

        km_raw = specs.get("kilometerstand", "")
        km_m = re.search(r"(\d+[\.\d]*)", km_raw.replace(" ", ""))
        record["mileage_km"] = int(km_m.group(1).replace(".", "")) if km_m else None

        cc_raw = specs.get("hubraum", "")
        cc_m = re.search(r"(\d+[\.\d]*)", cc_raw.replace(" ", ""))
        record["engine_displacement_cm3"] = int(cc_m.group(1).replace(".", "")) if cc_m else None

        p_raw = specs.get("leistung", "")
        kw_m = re.search(r"(\d+)\s*kw", p_raw, re.I)
        hp_m = re.search(r"\((\d+)\s*ps\)", p_raw, re.I)
        record["power_kw"] = int(kw_m.group(1)) if kw_m else None
        record["power_hp"] = int(hp_m.group(1)) if hp_m else (
            int(round(record["power_kw"] * 1.35962)) if record.get("power_kw") else None
        )

        trans_raw = specs.get("getriebe", "").lower()
        if "automatik" in trans_raw:
            record["transmission"] = "automata"
        elif "schalt" in trans_raw or "manuell" in trans_raw:
            record["transmission"] = "manuala"
        else:
            record["transmission"] = trans_raw or None

        record["fuel_type"] = specs.get("kraftstoffart")
        record["first_registration"] = specs.get("erstzulassung")
        record["euro_standard"] = specs.get("schadstoffklasse")
        record["doors"] = specs.get("anzahl der türen") or specs.get("anzahl türen")
        record["seats"] = specs.get("anzahl sitzplätze")
        record["color"] = specs.get("farbe (hersteller)") or specs.get("farbe")

        state_raw = specs.get("fahrzeugzustand", "").lower()
        record["condition"] = specs.get("fahrzeugzustand")
        if "unfallfrei" in state_raw:
            record["accident_free"] = True
            record["damaged"] = "neavariata"
        elif "beschädigt" in state_raw or "unfall" in state_raw:
            record["accident_free"] = False
            record["damaged"] = "avariata"
        else:
            record["accident_free"] = None
            record["damaged"] = None

        record["air_conditioning"] = specs.get("klimatisierung")

        # Features list
        features = []
        for f_el in soup.select("[data-testid*='features'] li, .bullet-list li, #features li"):
            f_text = f_el.get_text(strip=True)
            if f_text and f_text not in features:
                features.append(f_text)
        record["features"] = ", ".join(features) if features else None

        return record

    def enrich_from_existing_csv(self, csv_path: str | Path | None = None, output_csv: str | Path | None = None):
        """Enriches the 20,000 URLs already present in mobile_de.csv."""
        if csv_path is None or str(csv_path) == "data/raw/mobile_de.csv":
            candidates = [
                MOBILEDE_DATA_DIR / "mobile_de.csv",
            ]
            csv_path = next((p for p in candidates if p.exists()), candidates[0])
        csv_path = Path(csv_path)

        if not csv_path.exists():
            log.error(f"Input listings CSV not found at: {csv_path}")
            log.info("Please provide --input-csv <path> to specify the input file.")
            return

        log.info(f"Loading existing listings from {csv_path}...")
        df = pd.read_csv(csv_path)
        log.info(f"Loaded {len(df):,} listings from existing Mobile.de dataset.")

        processed_set = self.checkpoint.processed_ids
        to_scrape = df[~df["listing_id"].astype(str).isin(processed_set)]
        done_count = len(self.checkpoint.scraped_ids)
        log.info(
            f"Already scraped: {done_count:,} | Skipped/Processed: {len(processed_set):,} | "
            f"Remaining listings to enrich: {len(to_scrape):,}"
        )

        if len(to_scrape) == 0:
            log.info("All listings already enriched!")
            self.export_csv()
            return

        log.info("Launching stealth browser (Camoufox) with Cloudflare WARP rotation...")
        count = done_count
        start_time = time.time()

        try:
            with Camoufox(headless=True, humanize=False) as browser:
                page = setup_clean_page(browser)

                for idx, row in to_scrape.iterrows():
                    if count >= self.target:
                        log.info(f"Target count of {self.target:,} reached!")
                        break

                    lid = str(row["listing_id"])
                    url = str(row["listing_url"])

                    rec = None
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=18000)
                            html = page.content()

                            # 1. If Akamai sensor interstitial is executing (< 15KB), let Camoufox solve and auto-reload
                            if len(html) < 15000 and not is_hard_blocked(html):
                                for _ in range(5):
                                    time.sleep(1.0)
                                    html = page.content()
                                    if len(html) > 20000 or is_hard_blocked(html):
                                        break

                            # 2. Check for real Akamai hard-block ("Zugriff verweigert" / "Access Denied")
                            if is_hard_blocked(html):
                                log.warning(
                                    f"Akamai hard block on {url} (attempt {attempt+1}/{max_retries}). "
                                    f"Rotating Cloudflare WARP IP..."
                                )
                                rotate_warp_ip()
                                try:
                                    page.context.clear_cookies()
                                except Exception:
                                    pass
                                try:
                                    page.close()
                                except Exception:
                                    pass
                                page = setup_clean_page(browser)
                                time.sleep(2.0)
                                continue

                            # 3. Parse Technical Specifications
                            rec = self.parse_detail_html(html, url)
                            if rec:
                                break

                        except Exception as e:
                            log.warning(f"Notice on {url} (attempt {attempt+1}): {e}")
                            time.sleep(1.5)

                    if rec and rec.get("_status") == "expired":
                        final_record = build_canonical_record(row, rec, is_expired=True)
                        self._write_record(final_record)
                        self.checkpoint.add_expired(lid, url)
                        count += 1
                        if count % 20 == 0:
                            log.info(f"Enriched [{count:,}/{len(df):,}]: [EXPIRED/SOLD] ID={lid}")

                    elif rec:
                        final_record = build_canonical_record(row, rec, is_expired=False)
                        self._write_record(final_record)
                        self.checkpoint.add_id(lid)
                        count += 1

                        if count % 20 == 0 or count == 1:
                            elapsed = time.time() - start_time
                            rate = count / elapsed if elapsed > 0 else 0
                            log.info(
                                f"Enriched [{count:,}/{len(df):,}]: "
                                f"{final_record.get('brand', '')} {final_record.get('model', '')} | "
                                f"{final_record.get('body_type', 'N/A')} | "
                                f"{final_record.get('transmission', 'N/A')} | "
                                f"{final_record.get('engine_displacement_cm3', 'N/A')} cm³ | "
                                f"{final_record.get('price')} EUR"
                            )

                        # Periodic export every 250 listings
                        if count % 250 == 0:
                            self.checkpoint.save()
                            self.export_csv()

                    else:
                        log.warning(f"Could not extract {url} after {max_retries} attempts.")
                        self.checkpoint.add_failed(lid, url)

                    # Polite micro-sleep between requests to avoid rate limits
                    time.sleep(random.uniform(0.6, 1.2))

        finally:
            self.checkpoint.save()
            self._fh.close()
            self.export_csv(output_path=output_csv)

    def export_csv(self, output_path: str | Path | None = None):
        """Export raw JSONL data to CSV."""
        candidates = [
            self.jsonl_path,
            MOBILEDE_DATA_DIR / "mobile_de_full.jsonl",
        ]
        read_path = next((p for p in candidates if p.exists()), None)
        if not read_path:
            return
        records = []
        with open(read_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
        if records:
            df = pd.DataFrame(records)
            if output_path is None or str(output_path) == "data/raw/mobile_de_full.csv":
                output_path = MOBILEDE_DATA_DIR / "mobile_de_full.csv"
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False, encoding="utf-8-sig")
            log.info(f"Successfully exported {len(df):,} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Mobile.de Full Detail Scraper (All Specifications)")
    parser.add_argument("--enrich", action="store_true", default=True, help="Enrich existing 20,000 URLs with full detail specs")
    parser.add_argument("--target", type=int, default=20000, help="Target listing count (default: 20000)")
    parser.add_argument("--input-csv", type=str, default=None, help=f"Path to input base mobile_de.csv (default: {MOBILEDE_DATA_DIR / 'mobile_de.csv'})")
    parser.add_argument("--output-csv", type=str, default=None, help=f"Path for output full detail CSV (default: {MOBILEDE_DATA_DIR / 'mobile_de_full.csv'})")
    args = parser.parse_args()

    scraper = MobileDeFullScraper(target=args.target)
    if args.enrich:
        scraper.enrich_from_existing_csv(csv_path=args.input_csv, output_csv=args.output_csv)


if __name__ == "__main__":
    main()
