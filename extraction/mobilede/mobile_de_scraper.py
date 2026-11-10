"""
mobile_de_scraper.py - Scraper for mobile.de car listings powered by Camoufox.

Strategy:
  1. Price Bracket Slicing: Slices searches into balanced price brackets (€1,000 - €250,000)
     to overcome mobile.de's 50-page query cap and reach the 20,000 target.
  2. Filter Navigation: Opens the filter page, sets price range, clicks 'Offers' to reach
     suchen.mobile.de/fahrzeuge/search.html, then paginates with the 'Further' button.
  3. Card-Only Extraction: All data is extracted directly from search result cards
     (no detail page visits = 20x fewer requests = far less likely to get blocked).
  4. All Listings: Includes both organic and sponsored/promoted listings.
  5. Checkpointing: Fully resumable across brackets and pages.
"""

import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page

# Setup sys.path to access base_scraper and sibling modules
SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXTRACTION_DIR.parent

for p in [str(EXTRACTION_DIR), str(SCRIPT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from base_scraper import BaseScraper, DATA_DIR, ensure_dirs
MOBILEDE_DATA_DIR = DATA_DIR / "mobilede"


class MobileDeScraper(BaseScraper):

    # Granular price brackets designed to ensure sufficient capacity for 20,000+
    # listings despite mobile.de's 50-page (approx 950 cars) query cap.
    PRICE_BRACKETS = [
        (1000, 3000),      # Bracket 0: Budget / entry
        (3000, 4500),      # Bracket 1
        (4500, 6000),      # Bracket 2
        (6000, 8000),      # Bracket 3
        (8000, 10000),     # Bracket 4
        (10000, 12500),    # Bracket 5
        (12500, 15000),    # Bracket 6
        (15000, 17500),    # Bracket 7
        (17500, 20000),    # Bracket 8
        (20000, 24000),    # Bracket 9
        (24000, 28000),    # Bracket 10
        (28000, 31000),    # Bracket 11
        (31000, 34000),    # Bracket 12
        (34000, 37000),    # Bracket 13
        (37000, 40000),    # Bracket 14
        (40000, 43500),    # Bracket 15
        (43500, 47000),    # Bracket 16
        (47000, 51000),    # Bracket 17
        (51000, 55000),    # Bracket 18
        (55000, 60000),    # Bracket 19
        (60000, 65000),    # Bracket 20
        (65000, 70000),    # Bracket 21
        (70000, 75000),    # Bracket 22
        (75000, 80000),    # Bracket 23
    ]

    def __init__(
        self,
        headless: bool = False,
        target: int | None = None,
        bracket: int | None = None,
    ):
        super().__init__(headless=headless, target=target)
        self.selected_bracket = bracket

    @property
    def site_name(self) -> str:
        return "mobile_de"

    @property
    def homepage_url(self) -> str:
        return "https://www.mobile.de"

    def handle_cookie_consent(self, page: Page):
        """Accept cookie consent if the banner is present."""
        selectors = [
            'button[data-testid="mde-consent-modal-accept-btn"]',
            'button:has-text("Alle akzeptieren")',
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Zustimmen")',
            'button:has-text("Einverstanden")',
            '#mde-consent-modal-container button',
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    self.log.info(f"Dismissing cookie consent banner: {sel}")
                    btn.click()
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                pass

    def apply_filters_and_search(self, page: Page, min_price: int, max_price: int) -> bool:
        """
        Directly navigate to the search results page on suchen.mobile.de
        for the given price bracket, bypassing the www.mobile.de/s/auto filter page.
        """
        search_url = self.build_search_url_for_bracket(min_price, max_price, 1)
        self.log.info(f"Navigating directly to search results: {search_url}")
        success = self._navigate(page, search_url)
        if success:
            try:
                page.wait_for_selector('a[href*="details.html"], article', timeout=15000)
            except Exception:
                pass
        return success

    def build_search_url_for_bracket(self, min_price: int, max_price: int, page_num: int) -> str:
        """Build URL for suchen.mobile.de/fahrzeuge/search.html."""
        params = {
            "dam": "false",
            "isSearchRequest": "true",
            "p": f"{min_price}:{max_price}",
            "s": "Car",
            "vc": "Car",
            "ref": "dsp" if page_num == 1 else "srpNextPage",
        }
        if page_num > 1:
            params["pageNumber"] = str(page_num)
        base = "https://suchen.mobile.de/fahrzeuge/search.html"
        return f"{base}?{urllib.parse.urlencode(params)}"

    def build_search_url(self, page_num: int) -> str:
        """Default fallback URL builder."""
        return self.build_search_url_for_bracket(1000, 150000, page_num)

    def extract_listing_urls(self, page: Page) -> list[dict]:
        """Required by BaseScraper but not used in card-only mode."""
        return []

    def extract_detail(self, page: Page) -> dict | None:
        """Required by BaseScraper but not used in card-only mode."""
        return None

    def extract_cards(self, page: Page) -> list[dict]:
        """
        Extract all listing data directly from search result cards.
        No detail page visits needed — all data comes from the card DOM.
        Returns list of fully populated record dicts.
        """
        try:
            page.wait_for_selector('a[href*="details.html"], article', timeout=15000)
        except Exception:
            pass

        raw_cards = page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="details.html"]');
            const seen = new Set();

            links.forEach(link => {
                const href = link.getAttribute('href') || '';
                const idMatch = href.match(/id=(\\d+)/);
                if (!idMatch) return;
                const id = idMatch[1];
                if (seen.has(id)) return;
                seen.add(id);

                const card = link.closest('article') || link.closest('[data-testid*="listing"]') || link;

                // Brand from listing-title-card-view
                const brandEl = card.querySelector('[data-testid="listing-title-card-view"]');
                const brand = brandEl ? brandEl.innerText.trim() : '';

                // Full title (brand + model + description)
                const titleEl = card.querySelector('[data-testid*="-title"]');
                const fullTitle = titleEl ? titleEl.innerText.trim().replace(/\\n/g, ' ') : '';

                // Price
                const priceEl = card.querySelector('[data-testid="price-label"]');
                const priceText = priceEl ? priceEl.innerText.trim() : '';

                // Attributes (registration, mileage, power, fuel)
                const attrEl = card.querySelector('[data-testid="listing-details-attributes"]');
                const attributes = attrEl ? attrEl.innerText.trim() : '';

                // Seller info
                const sellerEl = card.querySelector('[data-testid="seller-info"]');
                const sellerText = sellerEl ? sellerEl.innerText.trim() : '';

                results.push({
                    id: id,
                    href: href,
                    brand: brand,
                    fullTitle: fullTitle,
                    priceText: priceText,
                    attributes: attributes,
                    sellerText: sellerText
                });
            });
            return results;
        }""")

        records = []
        for card in (raw_cards or []):
            record = self._parse_card(card)
            if record:
                records.append(record)
        return records

    def _parse_card(self, card: dict) -> dict | None:
        """Parse raw card data into a structured record."""
        listing_id = card.get("id")
        if not listing_id:
            return None

        record = {
            "listing_id": listing_id,
            "listing_url": f"https://suchen.mobile.de/fahrzeuge/details.html?id={listing_id}",
        }

        # Brand and model from card title
        brand_text = card.get("brand", "")
        full_title = card.get("fullTitle", "").replace("\n", " ")

        # Strip sponsored badge prefixes if present
        full_title = re.sub(r"^(?:Gesponsert|Sponsored)\s*", "", full_title, flags=re.IGNORECASE).strip()
        brand_text = re.sub(r"^(?:Gesponsert|Sponsored)\s*", "", brand_text, flags=re.IGNORECASE).strip()

        if brand_text:
            # First line is usually the brand, rest is model + description
            parts = brand_text.split("\n")
            record["brand"] = parts[0].strip() if parts else brand_text.strip()

        record["title"] = full_title

        # Extract model from title by removing brand prefix
        if record.get("brand") and full_title:
            model_part = full_title.replace(record["brand"], "", 1).strip()
            # Model is typically the first word/phrase after brand
            record["model"] = model_part.split("  ")[0].strip() if model_part else None
        else:
            record["model"] = None

        # Price
        price_text = card.get("priceText", "")
        price_match = re.search(r"([\d.]+)", price_text.replace(".", "").replace(",", "."))
        if price_match:
            try:
                # German format: 2.950 means 2950
                clean = price_text.replace("€", "").replace(".", "").replace(",", ".").strip()
                price_num = re.search(r"(\d+(?:\.\d+)?)", clean)
                if price_num:
                    record["price"] = float(price_num.group(1))
                    if record["price"] == int(record["price"]):
                        record["price"] = int(record["price"])
            except (ValueError, AttributeError):
                pass
        record["currency"] = "EUR"

        # Attributes: "EZ 05/2008 · 154.000 km · 128 kW (174 PS) · Benzin"
        attributes = card.get("attributes", "")
        self._parse_attributes_text(attributes, record)

        # Seller info: "Seller Name\n12345 City\nRating"
        seller_text = card.get("sellerText", "")
        self._parse_seller_info(seller_text, record)

        record["source"] = self.site_name

        return record

    def _parse_attributes_text(self, text: str, data: dict):
        """Parse bullet text like 'EZ 05/2008 · 154.000 km · 128 kW (174 PS) · Benzin'."""
        text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
        parts = re.split(r"\s*[•·\u00b7\u2022\ufffd]\s*", text)
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # "Unfallfrei" = accident-free
            if "unfallfrei" in part.lower():
                data["accident_free"] = True
                continue

            # First registration: "EZ 05/2008" or just "05/2008"
            fr_match = re.search(r"(?:EZ\s*)?(\d{2}/\d{4})", part, re.IGNORECASE)
            if fr_match and "first_registration" not in data:
                data["first_registration"] = fr_match.group(1)
                continue

            # Mileage: "154.000 km"
            km_match = re.search(r"([\d.,]+)\s*km", part, re.IGNORECASE)
            if km_match and "mileage_km" not in data:
                try:
                    data["mileage_km"] = int(km_match.group(1).replace(".", "").replace(",", ""))
                except ValueError:
                    pass
                continue

            # Power: "128 kW (174 PS)"
            kw_match = re.search(r"(\d+)\s*kW", part)
            hp_match = re.search(r"(\d+)\s*(?:PS|hp)", part)
            if kw_match:
                data["power_kw"] = int(kw_match.group(1))
            if hp_match:
                data["power_hp"] = int(hp_match.group(1))
            if kw_match or hp_match:
                continue

            # Fuel type
            fuel_map = {
                "benzin": "Petrol", "diesel": "Diesel", "petrol": "Petrol",
                "elektro": "Electric", "electric": "Electric",
                "hybrid": "Hybrid", "plug-in": "Plug-in Hybrid",
                "erdgas": "Natural Gas", "cng": "CNG", "lpg": "LPG",
            }
            lower = part.lower()
            for kw, name in fuel_map.items():
                if kw in lower and "fuel_type" not in data:
                    data["fuel_type"] = name
                    break
            else:
                # Transmission
                if ("schaltgetriebe" in lower or "manual" in lower) and "transmission" not in data:
                    data["transmission"] = "Manual"
                elif ("automatik" in lower or "automatic" in lower) and "transmission" not in data:
                    data["transmission"] = "Automatic"

    def _parse_seller_info(self, text: str, data: dict):
        """Parse seller info: 'Seller Name\\n12345 City\\n4.9 Sterne\\n(449)'."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return

        # First line is usually seller name (or "Privatanbieter")
        data["seller_name"] = lines[0]

        # Look for postal code + city pattern: "12345 City Name"
        for line in lines[1:]:
            postal_match = re.match(r"(\d{4,5})\s+(.+)", line)
            if postal_match:
                data["seller_postal_code"] = postal_match.group(1)
                data["seller_city"] = postal_match.group(2).rstrip(".")
                data["seller_country"] = "DE"
                break

    def go_to_next_page(self, page: Page, min_p: int, max_p: int, next_page_num: int) -> bool:
        """Advance to the next page using direct search URL navigation."""
        search_url = self.build_search_url_for_bracket(min_p, max_p, next_page_num)
        self.log.info(f"Advancing to page {next_page_num}: {search_url}")
        success = self._navigate(page, search_url)
        if success:
            try:
                page.wait_for_selector('a[href*="details.html"], article', timeout=15000)
            except Exception:
                pass
        return success

    def _scrape_loop(self, page: Page):
        """
        Card-only scraping loop. Iterates through price brackets and pages,
        extracting all data from search result cards without visiting detail pages.
        Only 1 request per page = ~50 requests per bracket = ~1150 total for all brackets.
        """
        if self.selected_bracket is not None:
            bracket_range = range(self.selected_bracket, min(self.selected_bracket + 1, len(self.PRICE_BRACKETS)))
            start_bracket = self.selected_bracket
        else:
            start_bracket = self.checkpoint.bracket_index
            bracket_range = range(start_bracket, len(self.PRICE_BRACKETS))

        try:
            for b_idx in bracket_range:
                min_p, max_p = self.PRICE_BRACKETS[b_idx]
                self.log.info(
                    f"\n{'='*70}\n"
                    f"Starting Price Bracket {b_idx + 1}/{len(self.PRICE_BRACKETS)}: "
                    f"€{min_p:,} – €{max_p:,}\n"
                    f"{'='*70}"
                )

                if b_idx == start_bracket and self.checkpoint.last_page > 0:
                    start_page = self.checkpoint.last_page + 1
                    search_url = self.build_search_url_for_bracket(min_p, max_p, start_page)
                    self.log.info(f"Resuming bracket {b_idx} at page {start_page} via {search_url}")
                    if not self._navigate(page, search_url):
                        continue
                else:
                    start_page = 1
                    if not self.apply_filters_and_search(page, min_p, max_p):
                        self.log.warning(f"Failed to apply filters for bracket {b_idx}, skipping.")
                        continue

                consecutive_empty = 0

                for page_num in range(start_page, 51):
                    if len(self.checkpoint.scraped_ids) >= self.TARGET_COUNT:
                        self.log.info(f"Target count of {self.TARGET_COUNT} reached!")
                        return

                    self.log.info(
                        f"[Bracket €{min_p:,}-€{max_p:,}] Page {page_num}/50 | "
                        f"Total: {len(self.checkpoint.scraped_ids)}/{self.TARGET_COUNT}"
                    )

                    self._sleep()

                    # Extract all data from cards on this page
                    cards = self.extract_cards(page)
                    if not cards:
                        consecutive_empty += 1
                        self.log.info(f"No cards found at page {page_num} for bracket €{min_p:,}-€{max_p:,}.")
                        if consecutive_empty >= 2:
                            break
                        continue

                    consecutive_empty = 0
                    new_cards = [
                        c for c in cards
                        if c["listing_id"] not in self.checkpoint.scraped_ids
                    ]
                    self.log.info(
                        f"Extracted {len(cards)} cards ({len(new_cards)} new)."
                    )

                    for record in new_cards:
                        if len(self.checkpoint.scraped_ids) >= self.TARGET_COUNT:
                            return

                        record["price_bracket"] = f"{min_p}-{max_p}"
                        record["scraped_at"] = datetime.now().isoformat()
                        self.writer.write(record)
                        self.checkpoint.add_id(record["listing_id"])
                        self.log.info(
                            f"[{len(self.checkpoint.scraped_ids)}/{self.TARGET_COUNT}] "
                            f"{record.get('brand', '')} {record.get('model', '')} | "
                            f"€{record.get('price', '')} | "
                            f"{record.get('mileage_km', '')} km | "
                            f"{record.get('fuel_type', '')} | "
                            f"{record.get('first_registration', '')}"
                        )

                    # Checkpoint after each page
                    self.checkpoint.bracket_index = b_idx
                    self.checkpoint.last_page = page_num
                    self.checkpoint.save()

                    # Advance to next page
                    if page_num < 50:
                        if not self.go_to_next_page(page, min_p, max_p, page_num + 1):
                            self.log.info(f"No further page available beyond page {page_num}.")
                            break

                # Bracket completed
                self.checkpoint.bracket_index = b_idx + 1
                self.checkpoint.last_page = 0
                self.checkpoint.save()
        except Exception:
            raise

    @staticmethod
    def _deep_get(d: dict, *keys):
        """Safely traverse nested dictionary keys."""
        for key in keys:
            if isinstance(d, dict):
                d = d.get(key)
            else:
                return None
        return d

    def export_csv(self, output_path: str | None = None):
        """Export raw JSONL data to CSV."""
        import pandas as pd

        candidates = [
            MOBILEDE_DATA_DIR / f"{self.site_name}.jsonl",
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
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if not records:
            self.log.warning("No records to export.")
            return

        df = pd.DataFrame(records)
        if output_path is None:
            output_path = str(MOBILEDE_DATA_DIR / f"{self.site_name}.csv")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        self.log.info(f"Successfully exported {len(df):,} records to {output_path}")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape mobile.de with Camoufox stealth browser")
    parser.add_argument(
        "--target", type=int, default=20000,
        help="Target number of listings to scrape (default: 20000)"
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Run browser with visible window (default: headless)"
    )
    parser.add_argument(
        "--bracket", type=int, default=None,
        help="Specific price bracket index (0-23)"
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="Export scraped JSONL data to CSV and exit"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help=f"Custom CSV export path (default: {MOBILEDE_DATA_DIR / 'mobile_de.csv'})"
    )
    args = parser.parse_args()

    scraper = MobileDeScraper(
        headless=not args.headed,
        target=args.target,
        bracket=args.bracket,
    )

    if args.export_csv:
        scraper.export_csv(output_path=args.output)
    else:
        scraper.run()
