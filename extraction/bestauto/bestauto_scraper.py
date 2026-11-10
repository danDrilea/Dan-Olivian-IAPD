"""
bestauto_scraper.py - High-Performance Requests + BeautifulSoup Scraper for bestauto.ro.

Features:
  - Direct HTTP requests + BeautifulSoup for 5x-10x scraping speed (~0.2s per listing)
  - Seamless Cloudflare WARP IP hotswap on HTTP 429/403 rate-limits
  - Price Bracket Slicing (€1,000 to €30,000+) to bypass BestAuto's 100-page query cap
  - Deduplication: automatically checks and skips all already scraped listings in checkpoint
  - 100% attribute extraction identical to ML schema (brand, model, price, mileage, engine, power, etc.)
  - Crash-proof checkpointing in data/checkpoints/bestauto_checkpoint.json
  - Atomic JSONL writes to data/raw/bestauto.jsonl
  - Automatic export to data/raw/bestauto.csv
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
import requests

# Ensure extraction directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXTRACTION_DIR.parent

for p in [str(EXTRACTION_DIR), str(SCRIPT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from base_scraper import Checkpoint, JSONLWriter, DATA_DIR, ensure_dirs
BESTAUTO_DATA_DIR = DATA_DIR / "bestauto"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class BestAutoScraper:
    """Production scraper for bestauto.ro powered by Requests + BeautifulSoup with Cloudflare WARP hotswap."""

    TARGET_COUNT: int = 25_000
    MAX_PAGES_PER_BRACKET: int = 100
    SLEEP_MIN: float = 0.15
    SLEEP_MAX: float = 0.35

    PRICE_BRACKETS = [
        (1000, 3000),      # Bracket 0: €1,000 - €3,000
        (3000, 5000),      # Bracket 1: €3,000 - €5,000
        (5000, 7000),      # Bracket 2: €5,000 - €7,000
        (7000, 10000),     # Bracket 3: €7,000 - €10,000
        (10000, 30000),    # Bracket 4: €10,000 - €30,000
        (30000, 100000),   # Bracket 5: €30,000 - €100,000 (Top-up safety bracket)
    ]

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(
        self,
        target: int | None = None,
        bracket: int | None = None,
        start_page: int | None = None,
    ):
        self.site_name = "bestauto"
        self.log = logging.getLogger(self.site_name)
        ensure_dirs()

        self.checkpoint = Checkpoint(self.site_name)
        self.writer = JSONLWriter(self.site_name)
        self.target_count = target or self.TARGET_COUNT
        self.selected_bracket = bracket

        if start_page is not None and start_page > 0:
            self.checkpoint.last_page = start_page - 1
            self.checkpoint.save()

        self._init_session()

    def _init_session(self):
        """Initialize or reset HTTP session with desktop browser headers."""
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)

    def _rotate_ip_if_possible(self) -> bool:
        """Rotate IP via Cloudflare WARP CLI if available."""
        warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
        if not os.path.exists(warp_cli):
            self.log.warning("Cloudflare WARP CLI not found at default path.")
            return False
        try:
            self.log.info("Detected IP rate-limit / block. Rotating Cloudflare WARP IP...")
            subprocess.run([warp_cli, "tunnel", "rotate-keys"], check=True, capture_output=True)
            subprocess.run([warp_cli, "disconnect"], check=True, capture_output=True)
            time.sleep(2)
            subprocess.run([warp_cli, "connect"], check=True, capture_output=True)
            time.sleep(3)
            try:
                new_ip = subprocess.check_output(["curl.exe", "-s", "https://api.ipify.org"], timeout=5).decode().strip()
                self.log.info(f"Cloudflare WARP rotated successfully. New IP: {new_ip}")
            except Exception:
                self.log.info("Cloudflare WARP rotated successfully.")
            self._init_session()
            return True
        except Exception as e:
            self.log.warning(f"Automatic WARP rotation failed: {e}")
            return False

    def fetch(self, url: str, max_retries: int = 5) -> str | None:
        """Fetch URL with retries, backoff, and Cloudflare WARP IP rotation on 429/403."""
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, timeout=12)

                # Rate-limit or Bot Block check
                if resp.status_code in (429, 403) or "denied access" in resp.text.lower():
                    self.log.warning(f"Rate-limit or anti-bot block (HTTP {resp.status_code}) on attempt {attempt+1}/{max_retries} for {url}")
                    if self._rotate_ip_if_possible():
                        time.sleep(5)
                    else:
                        cooldown = 30.0 + random.uniform(5.0, 15.0)
                        self.log.info(f"Waiting {cooldown:.1f}s cooldown before retry...")
                        time.sleep(cooldown)
                    continue

                if resp.status_code >= 500:
                    wait = 2 ** attempt + random.uniform(0.5, 1.5)
                    self.log.warning(f"Server error HTTP {resp.status_code}, retrying in {wait:.1f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code == 200:
                    return resp.text

                self.log.warning(f"Unexpected status HTTP {resp.status_code} for {url}")
                return None

            except Exception as e:
                wait = 2 ** attempt + random.uniform(0.5, 1.5)
                self.log.warning(f"Request error ({e}), retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)

        self.log.error(f"Failed to fetch {url} after {max_retries} attempts.")
        return None

    def _sleep(self):
        """Random polite delay between requests."""
        duration = random.uniform(self.SLEEP_MIN, self.SLEEP_MAX)
        time.sleep(duration)

    def build_search_url_for_bracket(self, min_price: int, max_price: int, page_num: int) -> str:
        """Build URL for search page with price bracket and 50 listings."""
        return (
            f"https://www.bestauto.ro/auto/?currency=eur"
            f"&minprice={min_price}&maxprice={max_price}&pagesize=50&pag={page_num}"
        )

    def extract_listing_urls(self, html: str) -> list[dict]:
        """Extract all car listing URLs and IDs from search page HTML."""
        soup = BeautifulSoup(html, "html.parser")
        items = []
        seen = set()

        for a in soup.select(".article-title a"):
            href = a.get("href", "").strip()
            if not href or "/anunt/" not in href:
                continue

            if not href.startswith("http"):
                href = "https://www.bestauto.ro" + href

            parent = a.find_parent(attrs={"data-articleid": True})
            id_attr = parent.get("data-articleid") if parent else None
            url_match = re.search(r"([a-zA-Z0-9]+)\.html", href)
            unique_id = id_attr or (url_match.group(1) if url_match else href)

            if unique_id in seen:
                continue
            seen.add(unique_id)

            items.append({
                "id": unique_id,
                "url": href,
                "title": a.get_text(strip=True),
            })

        return items

    def extract_detail(self, html: str) -> dict | None:
        """Extract complete structured car specifications from detail page HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Title
        h1 = soup.select_one(".detail-title h1, h1")
        title = h1.get_text(strip=True) if h1 else None
        if not title:
            return None

        record = {"title": title}

        # 2. Ad ID & Description
        desc_el = soup.select_one(".article-description")
        description_text = ""
        if desc_el:
            description_text = desc_el.get_text(" ", strip=True)
            id_m = re.search(r"ID\s*anun[țt]\s*:\s*(\d+)", description_text, re.I)
            if id_m:
                record["ad_id"] = id_m.group(1)

        # 3. Price & Currency (Only EUR)
        price_container = soup.select_one(".product-price")
        if price_container:
            spans = price_container.find_all("span")
            price_raw = spans[0].get_text(strip=True) if len(spans) > 0 else ""
            currency_raw = spans[1].get_text(strip=True).upper() if len(spans) > 1 else ""

            # Skip RON / LEI listings
            if "RON" in currency_raw or "LEI" in currency_raw:
                return None

            clean_p = price_raw.replace(".", "").replace(" ", "").replace(",", ".")
            m_price = re.search(r"(\d+(?:\.\d+)?)", clean_p)
            record["price"] = float(m_price.group(1)) if m_price else None
            record["currency"] = "EUR"
        else:
            return None

        # 4. Location
        loc_p = soup.select_one(".detail-info .medium-5 p")
        if loc_p:
            loc_parts = [p.strip() for p in loc_p.get_text(strip=True).split(",") if p.strip()]
            if len(loc_parts) >= 2:
                record["seller_county"] = loc_parts[0]
                record["seller_city"] = loc_parts[1]
            elif len(loc_parts) == 1:
                record["seller_county"] = loc_parts[0]
                record["seller_city"] = None
        else:
            record["seller_county"] = None
            record["seller_city"] = None

        # 5. Specifications from 'Specificații'
        specs = {}
        for item in soup.select(".article-attributes .attribute-item"):
            lbl = item.select_one(".attribute-label")
            val = item.select_one(".attribute-value")
            if lbl and val:
                k = lbl.get_text(strip=True)
                v = val.get_text(strip=True)
                if k:
                    specs[k] = v

        record["brand"] = specs.get("Marca")
        record["model"] = specs.get("Model")
        record["first_registration"] = specs.get("Data fabricatiei")
        record["body_type"] = specs.get("Categoria")
        record["fuel_type"] = specs.get("Motorizare")

        # Mileage clean
        km_str = (specs.get("Kilometraj") or "").replace(".", "").replace(" ", "").replace("km", "")
        m_km = re.search(r"(\d+)", km_str)
        record["mileage_km"] = int(m_km.group(1)) if m_km else None

        # Engine displacement clean (cm3)
        cm3_str = (specs.get("Capacitate cilindrica") or "").replace(".", "").replace(" ", "")
        m_cm3 = re.search(r"(\d+)", cm3_str)
        record["engine_displacement_cm3"] = int(m_cm3.group(1)) if m_cm3 else None

        # Power clean (hp)
        hp_str = (specs.get("Putere maxima") or "").replace(".", "").replace(" ", "")
        m_hp = re.search(r"(\d+)", hp_str)
        record["power_hp"] = int(m_hp.group(1)) if m_hp else None

        # Transmission with description keyword fallback
        trans = specs.get("Cutie de viteze")
        if not trans:
            text_to_search = f"{title} {description_text}".lower()
            if any(k in text_to_search for k in ["automata", "automat", "dsg", "tiptronic", "s-tronic", "dct"]):
                trans = "automata"
            elif any(k in text_to_search for k in ["manuala", "manual"]):
                trans = "manuala"
        record["transmission"] = trans

        record["euro_standard"] = specs.get("Norma euro")
        record["condition"] = specs.get("Stare")
        damaged = specs.get("Avariata")
        record["damaged"] = damaged
        record["accident_free"] = (damaged.lower() == "neavariata") if damaged else None

        record["color"] = specs.get("Culoare")
        record["doors"] = specs.get("Numar usi")
        record["air_conditioning"] = specs.get("Clima")
        record["features"] = specs.get("Dotari")

        return record

    def run(self):
        """Main scraping loop across price brackets."""
        self.log.info(f"Starting BestAuto scraper (Target: {self.target_count:,} listings)")
        self.log.info(f"Existing scraped listings in checkpoint: {len(self.checkpoint.scraped_ids):,}")

        if len(self.checkpoint.scraped_ids) >= self.target_count:
            self.log.info(f"Target count already satisfied ({len(self.checkpoint.scraped_ids):,}).")
            self.export_csv()
            return

        if self.selected_bracket is not None:
            bracket_range = range(self.selected_bracket, min(self.selected_bracket + 1, len(self.PRICE_BRACKETS)))
        else:
            start_b = min(self.checkpoint.bracket_index, len(self.PRICE_BRACKETS) - 1)
            bracket_range = range(start_b, len(self.PRICE_BRACKETS))

        try:
            for b_idx in bracket_range:
                min_p, max_p = self.PRICE_BRACKETS[b_idx]
                self.log.info(
                    f"\n{'='*70}\n"
                    f"Starting Price Bracket {b_idx + 1}/{len(self.PRICE_BRACKETS)}: "
                    f"€{min_p:,} – €{max_p:,}\n"
                    f"{'='*70}"
                )

                if (
                    b_idx == self.checkpoint.bracket_index
                    and self.checkpoint.last_page > 0
                    and self.checkpoint.last_page < self.MAX_PAGES_PER_BRACKET
                ):
                    start_page = self.checkpoint.last_page + 1
                    self.log.info(f"Resuming bracket {b_idx} at page {start_page}...")
                else:
                    start_page = 1

                consecutive_empty = 0

                for page_num in range(start_page, self.MAX_PAGES_PER_BRACKET + 1):
                    if len(self.checkpoint.scraped_ids) >= self.target_count:
                        self.log.info(f"Target count of {self.target_count:,} reached!")
                        return

                    search_url = self.build_search_url_for_bracket(min_p, max_p, page_num)
                    self.log.info(
                        f"[Bracket {b_idx + 1}: €{min_p:,}–€{max_p:,}] Page {page_num}/{self.MAX_PAGES_PER_BRACKET} | "
                        f"Progress: {len(self.checkpoint.scraped_ids):,}/{self.target_count:,}"
                    )

                    html = self.fetch(search_url)
                    if not html:
                        self.log.warning(f"Could not load search page {page_num}, moving to next.")
                        continue

                    listings = self.extract_listing_urls(html)
                    if not listings:
                        consecutive_empty += 1
                        self.log.info(f"No listings found on page {page_num} for bracket €{min_p:,}–€{max_p:,}.")
                        if consecutive_empty >= 3:
                            self.log.info(f"Bracket €{min_p:,}–€{max_p:,} exhausted. Moving to next bracket.")
                            break
                        continue

                    consecutive_empty = 0
                    new_listings = [item for item in listings if item["id"] not in self.checkpoint.scraped_ids]
                    self.log.info(f"Found {len(listings)} listings on page ({len(new_listings)} new).")

                    for item in new_listings:
                        if len(self.checkpoint.scraped_ids) >= self.target_count:
                            return

                        self._sleep()

                        detail_html = self.fetch(item["url"])
                        if not detail_html:
                            self.checkpoint.add_failed(item["url"])
                            continue

                        record = self.extract_detail(detail_html)
                        if record:
                            record["listing_id"] = item["id"]
                            record["listing_url"] = item["url"]
                            record["price_bracket"] = f"{min_p}-{max_p}"
                            record["source"] = self.site_name
                            record["scraped_at"] = datetime.now().isoformat()

                            self.writer.write(record)
                            self.checkpoint.add_id(item["id"])

                            self.log.info(
                                f"Scraped [{len(self.checkpoint.scraped_ids):,}/{self.target_count:,}]: "
                                f"{record.get('brand', '')} {record.get('model', '')} - "
                                f"{record.get('price', '')} EUR"
                            )
                        else:
                            self.log.warning(f"Failed to extract detail: {item['url']}")
                            self.checkpoint.add_failed(item["url"])

                    # Save checkpoint at end of search page
                    self.checkpoint.bracket_index = b_idx
                    self.checkpoint.last_page = page_num
                    self.checkpoint.save()

                # Bracket completed, prepare checkpoint for next bracket
                self.checkpoint.bracket_index = b_idx + 1
                self.checkpoint.last_page = 0
                self.checkpoint.save()

        finally:
            self.checkpoint.save()
            self.writer.close()
            self.export_csv()

    def export_csv(self, output_path: str | None = None):
        """Export raw JSONL data to CSV with clean ordered columns."""
        import pandas as pd

        candidates = [
            BESTAUTO_DATA_DIR / f"{self.site_name}.jsonl",
            SCRIPT_DIR / f"{self.site_name}.jsonl",
        ]
        jsonl_path = next((p for p in candidates if p.exists()), candidates[0])

        if not jsonl_path.exists():
            self.log.error(f"No data file found: {jsonl_path}")
            return

        records = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        records.append(rec)
                    except json.JSONDecodeError:
                        pass

        if not records:
            self.log.warning("No records to export.")
            return

        df = pd.DataFrame(records)

        cols_order = [
            "listing_id", "listing_url", "brand", "model", "title",
            "price", "currency", "price_bracket", "first_registration", "mileage_km",
            "engine_displacement_cm3", "power_hp", "fuel_type", "body_type",
            "transmission", "euro_standard", "accident_free", "condition",
            "seller_county", "seller_city", "color", "doors",
            "air_conditioning", "source", "scraped_at"
        ]
        existing_cols = [c for c in cols_order if c in df.columns]
        extra_cols = [c for c in df.columns if c not in cols_order]
        df = df[existing_cols + extra_cols]

        if output_path is None:
            output_path = str(BESTAUTO_DATA_DIR / f"{self.site_name}.csv")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        self.log.info(f"Successfully exported {len(df):,} records to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="BestAuto.ro Car Scraper (Fast BeautifulSoup Engine)")
    parser.add_argument("--headed", action="store_true", help="Ignored (kept for backwards compatibility)")
    parser.add_argument("--target", type=int, default=25_000, help="Target listing count (default: 25000)")
    parser.add_argument("--bracket", type=int, default=None, help="Scrape only a specific bracket index (0-5)")
    parser.add_argument("--start-page", type=int, default=None, help="Force start from page number")
    parser.add_argument("--export-csv", action="store_true", help="Export existing JSONL to CSV and exit")
    parser.add_argument("--output", type=str, default=None, help=f"Custom CSV export path (default: {BESTAUTO_DATA_DIR / 'bestauto.csv'})")
    args = parser.parse_args()

    scraper = BestAutoScraper(
        target=args.target,
        bracket=args.bracket,
        start_page=args.start_page,
    )

    if args.export_csv:
        scraper.export_csv(output_path=args.output)
        return

    scraper.run()


if __name__ == "__main__":
    main()
