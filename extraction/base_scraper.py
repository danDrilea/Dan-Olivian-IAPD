"""
base_scraper.py - Base scraper engine powered by Camoufox (Stealth Firefox).

Architecture:
  - Camoufox provides C++ level anti-fingerprint stealth (Canvas, WebGL, Audio,
    TLS JA4, Fonts, Humanized cursor movements) to defeat Akamai & Cloudflare.
  - BaseScraper manages browser lifecycle, rate-limiting, retries, and checkpointing.
  - JSONLWriter provides crash-safe incremental saving.
  - Checkpoint tracks scraped IDs and last page visited for 100% resume capability.
  - Subclasses implement site-specific extraction methods.
"""

import os
import atexit
import json
import time
import random
import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime

from camoufox.sync_api import Camoufox
from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Directories & Storage
# ---------------------------------------------------------------------------
EXTRACTION_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXTRACTION_DIR.parent
DATA_DIR = REPO_ROOT / "data"


def ensure_dirs(site_name: str | None = None):
    """Ensure data storage directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if site_name:
        (DATA_DIR / site_name).mkdir(parents=True, exist_ok=True)


class AntiBotBlockException(Exception):
    """Raised when an anti-bot block (Akamai/Cloudflare) is detected to immediately halt scraping."""
    pass


class Checkpoint:
    """Tracks scraping progress to allow seamless resuming."""

    def __init__(self, site_name: str):
        self.site_name = site_name
        self.site_dir = DATA_DIR / site_name
        self.site_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.site_dir / f"{site_name}_checkpoint.json"
        self.data = self._load()

    def _load(self) -> dict:
        default_data = {
            "scraped_ids": [],
            "bracket_index": 0,
            "last_page": 0,
            "total_scraped": 0,
            "last_updated": None,
            "failed_urls": [],
        }
        candidate_paths = [
            self.path,
            self.path.with_suffix(".tmp"),
            DATA_DIR / "checkpoints" / f"{self.site_name}_checkpoint.json",
            DATA_DIR / "raw" / f"{self.site_name}_checkpoint.json",
        ]
        for p in candidate_paths:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "scraped_ids" in data:
                            return data
                except Exception:
                    pass
        return default_data

    def save(self):
        """Immediately write checkpoint to disk atomically to prevent corruption."""
        self.data["last_updated"] = datetime.now().isoformat()
        temp_path = self.path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            pass

    @property
    def scraped_ids(self) -> set:
        return set(self.data.get("scraped_ids", []))

    def add_id(self, listing_id: str):
        """Add listing ID and immediately persist checkpoint to disk."""
        if listing_id not in self.data["scraped_ids"]:
            self.data["scraped_ids"].append(listing_id)
            self.data["total_scraped"] = len(self.data["scraped_ids"])
            self.save()

    def add_failed(self, url: str):
        if url not in self.data["failed_urls"]:
            self.data["failed_urls"].append(url)
            self.save()

    @property
    def bracket_index(self) -> int:
        return self.data.get("bracket_index", 0)

    @bracket_index.setter
    def bracket_index(self, val: int):
        self.data["bracket_index"] = val
        self.save()

    @property
    def last_page(self) -> int:
        return self.data.get("last_page", 0)

    @last_page.setter
    def last_page(self, val: int):
        self.data["last_page"] = val
        self.save()


class JSONLWriter:
    """Append-only JSONL writer with atomic OS fsync for 100% crash-safety."""

    def __init__(self, site_name: str):
        self.site_dir = DATA_DIR / site_name
        self.site_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.site_dir / f"{site_name}.jsonl"
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, record: dict):
        """Write record and force OS to flush directly to physical disk."""
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        try:
            os.fsync(self._fh.fileno())
        except Exception:
            pass

    def close(self):
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Base Scraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """
    Abstract base scraper using Camoufox stealth browser.

    Subclasses must implement:
      - site_name (property)
      - homepage_url (property)
      - build_search_url(page_num)
      - extract_listing_urls(page) -> list[dict]
      - extract_detail(page) -> dict | None
    """

    TARGET_COUNT: int = 20_000
    HEADLESS: bool = False
    SLEEP_MIN: float = 6.0
    SLEEP_MAX: float = 10.0
    MAX_RETRIES: int = 3
    TIMEOUT_MS: int = 30_000
    MAX_CONSECUTIVE_BLOCKS: int = 3
    BLOCK_COOLDOWN: float = 20.0

    def __init__(
        self,
        headless: bool = False,
        target: int | None = None,
        humanize: bool = True,
    ):
        self.HEADLESS = headless
        if target is not None:
            self.TARGET_COUNT = target
        self.humanize = humanize
        self.log = logging.getLogger(self.site_name)
        ensure_dirs()
        self.checkpoint = Checkpoint(self.site_name)
        self.writer = JSONLWriter(self.site_name)

        # Register exit handlers to guarantee data is saved if program stops
        atexit.register(self.checkpoint.save)
        atexit.register(self.writer.close)

    # ----- Abstract interface -----

    @property
    @abstractmethod
    def site_name(self) -> str:
        ...

    @property
    @abstractmethod
    def homepage_url(self) -> str:
        ...

    @abstractmethod
    def build_search_url(self, page_num: int) -> str:
        ...

    @abstractmethod
    def extract_listing_urls(self, page: Page) -> list[dict]:
        """Extract list of {'id': str, 'url': str} from a search page."""
        ...

    @abstractmethod
    def extract_detail(self, page: Page) -> dict | None:
        """Extract all features from a detail page. Return None on failure."""
        ...

    # ----- Utilities -----

    def _sleep(self):
        """Random polite jitter between actions."""
        time.sleep(random.uniform(self.SLEEP_MIN, self.SLEEP_MAX))

    def _is_blocked(self, page: Page, response=None) -> bool:
        """Check if page is an Akamai / Cloudflare block page or returned 403/429."""
        try:
            # 1. Check HTTP status code if response is available
            if response and response.status in (403, 429):
                self.log.critical(f"Server returned HTTP status {response.status}!")
                return True

            # 2. Check page title
            title = page.title().lower()
            if "access denied" in title or "attention required" in title or "403 forbidden" in title:
                return True

            # 3. Check page content for known anti-bot challenge/error phrases
            content = page.content()
            block_phrases = [
                "Error Reference:",
                "unfortunately had to deny access",
                "denied access to our data",
                "ray ID:",
                "403 Forbidden",
            ]
            return any(phrase.lower() in content.lower() for phrase in block_phrases)
        except Exception:
            return False

    def _rotate_ip_if_possible(self) -> bool:
        """Attempt to rotate IP using Cloudflare WARP CLI if available."""
        warp_cli = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
        if not os.path.exists(warp_cli):
            return False
        try:
            self.log.info("Detected IP block. Attempting automatic IP rotation via Cloudflare WARP...")
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
            return True
        except Exception as e:
            self.log.warning(f"Automatic WARP rotation failed: {e}")
            return False

    def _navigate(self, page: Page, url: str, retries: int = 0) -> bool:
        """Navigate to URL with retry logic. Self-heals on 403 blocks with 45s cooldown and WARP rotation."""
        max_block_retries = 5
        for block_attempt in range(max_block_retries):
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.TIMEOUT_MS)
                if self._is_blocked(page, response):
                    status_str = f" (HTTP {response.status})" if response else ""
                    self.log.warning(
                        f"Anti-bot block / rate-limit detected{status_str} at {url} "
                        f"(attempt {block_attempt + 1}/{max_block_retries})"
                    )
                    self._rotate_ip_if_possible()
                    try:
                        page.context.clear_cookies()
                    except Exception:
                        pass
                    cooldown = 45.0 + random.uniform(5.0, 15.0)
                    self.log.info(f"Waiting {cooldown:.1f}s for Akamai rate-limit window to reset before retry...")
                    time.sleep(cooldown)
                    continue
                return True
            except AntiBotBlockException:
                raise
            except Exception as e:
                if "Target closed" in str(e) or "Connection closed" in str(e):
                    raise
                if retries < self.MAX_RETRIES:
                    wait = 2 ** (retries + 1) + random.random()
                    self.log.warning(f"Navigation error ({e}), retrying in {wait:.1f}s ({retries + 1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    return self._navigate(page, url, retries + 1)
                else:
                    self.log.error(f"Failed to navigate after {self.MAX_RETRIES} retries: {url}")
                    return False
        
        self.log.critical(f"Exhausted {max_block_retries} block retries at {url}. Halting.")
        raise AntiBotBlockException(f"Persistent access denied at {url}")

    def _navigate_detail(self, page: Page, url: str) -> bool:
        """Navigate to a detail page with graceful 403 handling.
        A single car returning 403 (deleted/restricted listing) does NOT halt the scraper.
        Instead it skips that car and applies a cooldown. Only raises AntiBotBlockException
        if MAX_CONSECUTIVE_BLOCKS consecutive detail pages are blocked (real IP ban)."""
        if not hasattr(self, '_consecutive_detail_blocks'):
            self._consecutive_detail_blocks = 0
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.TIMEOUT_MS)
            if self._is_blocked(page, response):
                self._consecutive_detail_blocks += 1
                status_str = f" (HTTP {response.status})" if response else ""
                self.log.warning(
                    f"Detail page blocked{status_str}: {url} "
                    f"({self._consecutive_detail_blocks}/{self.MAX_CONSECUTIVE_BLOCKS} consecutive)"
                )
                if self._consecutive_detail_blocks >= self.MAX_CONSECUTIVE_BLOCKS:
                    self.log.critical(
                        f"{self.MAX_CONSECUTIVE_BLOCKS} consecutive detail pages blocked — "
                        f"IP is likely rate-limited. Halting to protect IP."
                    )
                    raise AntiBotBlockException(
                        f"{self.MAX_CONSECUTIVE_BLOCKS} consecutive blocks, last at {url}"
                    )
                # Single block: cooldown and skip this car
                self.log.info(f"Cooling down {self.BLOCK_COOLDOWN}s before next request...")
                time.sleep(self.BLOCK_COOLDOWN)
                return False
            # Success — reset consecutive counter
            self._consecutive_detail_blocks = 0
            return True
        except AntiBotBlockException:
            raise
        except Exception as e:
            # Non-block errors (timeout, frame detached, etc.) — retry normally
            try:
                wait = 3.0 + random.random() * 2
                self.log.warning(f"Detail navigation error ({e}), retrying in {wait:.1f}s")
                time.sleep(wait)
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.TIMEOUT_MS)
                if self._is_blocked(page, response):
                    self._consecutive_detail_blocks += 1
                    return False
                self._consecutive_detail_blocks = 0
                return True
            except Exception:
                self.log.error(f"Failed to navigate to detail: {url}")
                return False

    def handle_cookie_consent(self, page: Page):
        """Override in subclass to handle cookie consent dialogs."""
        pass

    # ----- Main scraping pipeline -----

    def run(self):
        """Main scraping loop with Camoufox stealth browser."""
        already = len(self.checkpoint.scraped_ids)
        remaining = self.TARGET_COUNT - already
        self.log.info(
            f"Starting {self.site_name} scraper with Camoufox. "
            f"Target: {self.TARGET_COUNT}, Already scraped: {already}, "
            f"Remaining: {remaining}"
        )
        if remaining <= 0:
            self.log.info("Target already reached.")
            return

        camoufox_options = {
            "headless": self.HEADLESS,
            "humanize": self.humanize,
            "os": "windows",
        }

        try:
            with Camoufox(**camoufox_options) as browser:
                page = browser.new_page()

                # Set English language cookies
                try:
                    page.context.add_cookies([
                        {"name": "mde-lang", "value": "en", "domain": ".mobile.de", "path": "/"},
                        {"name": "locale", "value": "en", "domain": ".mobile.de", "path": "/"},
                    ])
                except Exception:
                    pass

                # Warmup: visit homepage and accept cookies
                self.log.info(f"Warming up on {self.homepage_url}...")
                warmup_resp = None
                try:
                    warmup_resp = page.goto(self.homepage_url, wait_until="domcontentloaded", timeout=self.TIMEOUT_MS)
                    time.sleep(3)
                    self.handle_cookie_consent(page)
                    time.sleep(2)
                except Exception as e:
                    self.log.warning(f"Warmup notice: {e}")

                if self._is_blocked(page, warmup_resp):
                    status_str = f" (HTTP {warmup_resp.status})" if warmup_resp else ""
                    self.log.warning(f"Anti-bot block detected{status_str} on homepage warmup.")
                    if self._rotate_ip_if_possible():
                        self.log.info("Retrying homepage warmup with fresh IP...")
                        time.sleep(3)
                        warmup_resp = page.goto(self.homepage_url, wait_until="domcontentloaded", timeout=self.TIMEOUT_MS)
                        self.handle_cookie_consent(page)
                        time.sleep(2)
                    if self._is_blocked(page, warmup_resp):
                        self.log.critical(f"ANTI-BOT BLOCK DETECTED{status_str} on homepage! Halting immediately.")
                        self.checkpoint.save()
                        self.writer.close()
                        return

                try:
                    self._scrape_loop(page)
                except AntiBotBlockException as e:
                    self.log.critical(
                        f"\n{'='*70}\n"
                        f"SCRAPER HALTED IMMEDIATELY: {e}\n"
                        f"Progress has been safely saved in the checkpoint.\n"
                        f"No further requests will be sent to protect your IP.\n"
                        f"{'='*70}\n"
                    )
                except KeyboardInterrupt:
                    self.log.info("Interrupted by user. Progress saved in checkpoint.")
                finally:
                    self.checkpoint.save()
                    self.writer.close()
        except KeyboardInterrupt:
            self.log.info("Interrupted by user. Progress saved in checkpoint.")
        except Exception as e:
            if "Target closed" in str(e) or "Connection closed" in str(e):
                self.log.info("Browser session ended.")
            else:
                self.log.error(f"Scraper error: {e}")

        final = len(self.checkpoint.scraped_ids)
        self.log.info(f"Session finished. Total records: {final}. Saved to {self.writer.path}")

    def _scrape_loop(self, page: Page):
        """Paginates search results and extracts details."""
        start_page = max(self.checkpoint.last_page, 1)
        current_page = start_page
        consecutive_empty = 0

        while len(self.checkpoint.scraped_ids) < self.TARGET_COUNT:
            search_url = self.build_search_url(current_page)
            self.log.info(
                f"Page {current_page} | "
                f"Progress: {len(self.checkpoint.scraped_ids)}/{self.TARGET_COUNT}"
            )

            if not self._navigate(page, search_url):
                consecutive_empty += 1
                if consecutive_empty >= 5:
                    self.log.error("5 consecutive page navigation failures. Stopping.")
                    break
                current_page += 1
                continue

            self._sleep()

            listings = self.extract_listing_urls(page)
            if not listings:
                consecutive_empty += 1
                self.log.warning(f"No listings found on page {current_page}.")
                if consecutive_empty >= 5:
                    self.log.error("5 consecutive empty pages. Stopping.")
                    break
                current_page += 1
                continue

            consecutive_empty = 0
            new_listings = [
                l for l in listings
                if l["id"] not in self.checkpoint.scraped_ids
            ]
            self.log.info(
                f"Found {len(listings)} listings on page ({len(new_listings)} new)."
            )

            for listing in new_listings:
                if len(self.checkpoint.scraped_ids) >= self.TARGET_COUNT:
                    break

                self._sleep()

                if not self._navigate(page, listing["url"]):
                    self.checkpoint.add_failed(listing["url"])
                    continue

                record = self.extract_detail(page)
                if record:
                    record["listing_id"] = listing["id"]
                    record["listing_url"] = listing["url"]
                    record["source"] = self.site_name
                    record["scraped_at"] = datetime.now().isoformat()
                    self.writer.write(record)
                    self.checkpoint.add_id(listing["id"])
                    self.log.info(
                        f"Scraped [{len(self.checkpoint.scraped_ids)}/{self.TARGET_COUNT}]: "
                        f"{record.get('brand', '')} {record.get('model', '')} - "
                        f"{record.get('price', '')} {record.get('currency', 'EUR')}"
                    )
                else:
                    self.log.warning(f"Failed to extract detail: {listing['url']}")
                    self.checkpoint.add_failed(listing["url"])

            # Save checkpoint after each search results page
            self.checkpoint.last_page = current_page
            self.checkpoint.save()
            current_page += 1

    # ----- Export to CSV -----

    def export_csv(self, output_path: str | None = None):
        """Export raw JSONL data to CSV."""
        import pandas as pd

        candidates = [
            DATA_DIR / self.site_name / f"{self.site_name}.jsonl",
            DATA_DIR / "raw" / f"{self.site_name}.jsonl",
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
            output_path = str(DATA_DIR / self.site_name / f"{self.site_name}.csv")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        self.log.info(f"Successfully exported {len(df)} records to {output_path}")
