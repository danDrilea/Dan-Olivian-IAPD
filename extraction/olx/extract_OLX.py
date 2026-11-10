import csv
import json
import re
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlencode, urlparse, urlunparse
from datetime import datetime

from bs4 import BeautifulSoup
from curl_cffi import requests


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.olx.ro"
CARS_URL = "https://www.olx.ro/auto-masini-moto-ambarcatiuni/autoturisme/"

TOTAL_TARGET = 30000

YEAR_START = 2000
YEAR_END = 2026

SAVE_BATCH_SIZE = 500
MAX_PAGES_PER_SEARCH = 25
MAX_WORKERS = 10
REQUEST_DELAY = 0.25
MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
OUTPUT_DIR = REPO_ROOT / "data" / "olx"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JSONL_FILE = OUTPUT_DIR / "cars.jsonl"
CSV_FILE = OUTPUT_DIR / "cars.csv"
COUNTS_CACHE_FILE = OUTPUT_DIR / "counts_cache.json"

# False: reuse cached counts and calculate only missing counts.
# True: recalculate all preliminary counts.
REFRESH_COUNTS = False

BODY_TYPES = OrderedDict([
    ("Cabrio", "cabriolet"),
    ("Sedan", "sedan"),
    ("Coupe", "coupe"),
    ("Pickup", "pickup"),
    ("Hatchback", "hatchback"),
    ("Estate car", "estate-car"),
    ("Off-road vehicle", "off-road-vehicle"),
    ("SUV", "suv"),
])

FUEL_TYPES = OrderedDict([
    ("Petrol", "petrol"),
    ("Diesel", "diesel"),
    ("LPG", "lpg"),
    ("Hybrid", "hybrid"),
    ("Plug-in hybrid", "plugin-hybrid"),
    ("Electric", "electric"),
    ("CNG/LNG", "gnc-gnl"),
])


# ============================================================
# TERMINAL STATUS
# ============================================================

print_lock = threading.Lock()


def status(message):
    """Update the current terminal line instead of printing a new one."""
    with print_lock:
        print(f"\r{message:<140}", end="", flush=True)


def log(message=""):
    """Print a permanent message on a fresh line."""
    with print_lock:
        print(f"\r{' ' * 140}\r{message}", flush=True)


# ============================================================
# HTTP SESSIONS
# ============================================================

_thread_local = threading.local()


def get_session():
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session(
            impersonate="chrome"
        )
    return _thread_local.session


def get_page(url, expected_search=False):
    """Fetch a page with retries, keeping routine output quiet."""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = get_session().get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            if response.status_code == 404:
                return None

            if response.status_code in (403, 429):
                time.sleep(min(2 ** attempt, 20))
                continue

            response.raise_for_status()
            html = response.text

            if expected_search:
                recognizable = (
                    "l-card" in html
                    or "category-count-links" in html
                    or "Nu am găsit" in html
                    or "Nu am gasit" in html
                )

                if not recognizable and attempt < MAX_RETRIES:
                    time.sleep(REQUEST_DELAY * attempt)
                    continue

            time.sleep(REQUEST_DELAY)
            return html

        except Exception as exc:
            if attempt == MAX_RETRIES:
                log(f"Request failed: {exc}")
                return None

            time.sleep(min(attempt * 1.5, 8))

    return None


# ============================================================
# SEARCH URLS
# ============================================================

def build_search_url(body_value, fuel_value, year, page=1):
    params = [
        ("currency", "EUR"),
        ("search[order]", "created_at:desc"),
        ("search[filter_enum_petrol][0]", fuel_value),
        ("search[filter_float_year:from]", str(year)),
        ("search[filter_float_year:to]", str(year)),
        ("search[filter_enum_car_body][0]", body_value),
        ("view", "grid"),
    ]

    if page > 1:
        params.append(("page", str(page)))

    return CARS_URL + "?" + urlencode(params)


def normalize_listing_url(url):
    absolute_url = urljoin(BASE_URL, url)
    parsed = urlparse(absolute_url)

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        "",
        "",
        "",
    ))


def combo_key(body_value, fuel_value, year):
    return f"{year}|{body_value}|{fuel_value}"


# ============================================================
# PRELIMINARY COUNT EXTRACTION
# ============================================================

def parse_count(text):
    if not text:
        return 0

    value = text.strip().lower().replace("\xa0", " ")
    value = value.replace(" ", "")

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([km])?", value)

    if not match:
        return 0

    number_text, suffix = match.groups()

    if suffix:
        number = float(number_text.replace(",", "."))
        multiplier = 1000 if suffix == "k" else 1_000_000
        return int(number * multiplier)

    digits = re.sub(r"\D", "", number_text)
    return int(digits) if digits else 0


def extract_brand_count_sum(html):
    soup = BeautifulSoup(html, "html.parser")

    count_list = soup.select_one(
        'ul[data-testid="category-count-links"]'
    )

    if count_list:
        total = 0

        for item in count_list.select("li"):
            label = item.select_one(
                'span[data-nx-name="Label1"]'
            )

            if label:
                total += parse_count(
                    label.get_text(" ", strip=True)
                )

        return total

    page_text = soup.get_text(" ", strip=True).lower()

    no_results_phrases = (
        "nu am găsit",
        "nu am gasit",
        "nu există anunțuri",
        "nu exista anunturi",
        "no results",
        "no listings",
    )

    if any(phrase in page_text for phrase in no_results_phrases):
        return 0

    # Preserve the original behavior: a recognizable listing page
    # without a count list is treated as zero.
    if soup.select_one(
        'div[data-cy="l-card"], div[data-testid="l-card"]'
    ):
        return 0

    return None


def estimate_combo_count(
    body_name,
    body_value,
    fuel_name,
    fuel_value,
    year,
):
    url = build_search_url(body_value, fuel_value, year)
    html = get_page(url, expected_search=True)

    if html is None:
        return None

    return extract_brand_count_sum(html)


# ============================================================
# PRELIMINARY COUNT CACHE
# ============================================================

def load_counts_cache():
    if REFRESH_COUNTS:
        log("Count-cache refresh enabled.")
        return {}

    if not COUNTS_CACHE_FILE.exists():
        log("No preliminary count cache found.")
        return {}

    try:
        with COUNTS_CACHE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        counts = data.get("counts", {})

        valid_counts = {
            key: value
            for key, value in counts.items()
            if isinstance(value, int) and value >= 0
        }

        log(
            f"Loaded {len(valid_counts):,} cached counts "
            f"from {COUNTS_CACHE_FILE}"
        )

        return valid_counts

    except (json.JSONDecodeError, OSError, AttributeError) as exc:
        log(f"Could not read count cache: {exc}")
        return {}


def save_counts_cache(counts):
    temp_file = COUNTS_CACHE_FILE.with_suffix(".tmp")

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "year_start": YEAR_START,
        "year_end": YEAR_END,
        "body_types": dict(BODY_TYPES),
        "fuel_types": dict(FUEL_TYPES),
        "counts": counts,
    }

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    temp_file.replace(COUNTS_CACHE_FILE)


def discover_all_counts():
    counts = load_counts_cache()
    combinations = []

    for year in range(YEAR_START, YEAR_END + 1):
        for body_name, body_value in BODY_TYPES.items():
            for fuel_name, fuel_value in FUEL_TYPES.items():
                key = combo_key(body_value, fuel_value, year)

                if key not in counts:
                    combinations.append((
                        key,
                        body_name,
                        body_value,
                        fuel_name,
                        fuel_value,
                        year,
                    ))

    total_combinations = (
        len(BODY_TYPES)
        * len(FUEL_TYPES)
        * (YEAR_END - YEAR_START + 1)
    )

    cached_count = total_combinations - len(combinations)

    log(
        f"Count estimates: {cached_count:,}/{total_combinations:,} cached"
        f" | Remaining: {len(combinations):,}"
    )

    if not combinations:
        log("All preliminary counts are already cached.")
        return counts

    completed = 0
    failed = 0
    total_missing = len(combinations)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                estimate_combo_count,
                body_name,
                body_value,
                fuel_name,
                fuel_value,
                year,
            ): (key, year, body_name, fuel_name)
            for (
                key,
                body_name,
                body_value,
                fuel_name,
                fuel_value,
                year,
            ) in combinations
        }

        for future in as_completed(futures):
            key, year, body_name, fuel_name = futures[future]

            try:
                count = future.result()
            except Exception:
                count = None

            completed += 1

            if count is None:
                failed += 1
            else:
                counts[key] = int(count)
                save_counts_cache(counts)

            result = (
                f"{count:,}" if count is not None else "retry next run"
            )

            status(
                f"Estimating counts: {completed:,}/{total_missing:,}"
                f" | Failed: {failed}"
                f" | Last: {body_name} / {fuel_name} / {year}: {result}"
            )

    print()

    if failed:
        log(
            f"{failed:,} counts could not be estimated. "
            "They will be retried on the next run."
        )
    else:
        log("All preliminary counts have been saved.")

    return counts


# ============================================================
# TARGET ALLOCATION
# ============================================================

def allocate_targets(total_target, counts):
    valid_counts = {
        key: max(0, int(value))
        for key, value in counts.items()
    }

    total_count = sum(valid_counts.values())

    if total_target <= 0 or total_count <= 0:
        return {key: 0 for key in valid_counts}

    exact = {
        key: total_target * count / total_count
        for key, count in valid_counts.items()
    }

    targets = {
        key: int(value)
        for key, value in exact.items()
    }

    remaining = total_target - sum(targets.values())

    remainder_order = sorted(
        exact.keys(),
        key=lambda key: exact[key] - targets[key],
        reverse=True,
    )

    for key in remainder_order[:remaining]:
        targets[key] += 1

    return targets


# ============================================================
# LISTING EXTRACTION
# ============================================================

def extract_listing_cards(html):
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(
        'div[data-cy="l-card"], div[data-testid="l-card"]'
    )

    results = []

    for card in cards:
        link = card.select_one(
            'a[href*="/d/oferta/"], a[href*="/oferta/"]'
        )

        if not link or not link.get("href"):
            continue

        url = normalize_listing_url(link["href"])
        title = link.get("title") or link.get_text(" ", strip=True)

        if not title:
            title_node = card.select_one("h4, h6")
            if title_node:
                title = title_node.get_text(" ", strip=True)

        price_node = card.select_one('[data-testid="ad-price"]')
        posted_node = card.select_one('[data-testid="location-date"]')

        results.append({
            "URL": url,
            "Title": title.strip(),
            "Listing price": (
                price_node.get_text(" ", strip=True)
                if price_node else ""
            ),
            "Listing location/date": (
                posted_node.get_text(" ", strip=True)
                if posted_node else ""
            ),
        })

    return results


# ============================================================
# DETAIL PAGE EXTRACTION
# ============================================================

def clean_text(element):
    return element.get_text(" ", strip=True) if element else ""


def extract_detail_features(soup):
    features = {}

    # Paragraph-based parameter layouts.
    for container in soup.select(
        'div[data-testid="ad-parameters-container"], '
        'div[data-nx-name="ListContainer"]'
    ):
        for element in container.find_all("p"):
            text = element.get_text(" ", strip=True)

            if not text:
                continue

            if ":" in text:
                label, value = text.split(":", 1)
                label = label.strip().rstrip(":")
                value = value.strip()

                if label and value:
                    features[label] = value
            else:
                features.setdefault("Seller type", text)

    # Definition lists.
    for dl in soup.select("dl"):
        for term in dl.find_all("dt"):
            value_node = term.find_next_sibling("dd")

            if not value_node:
                continue

            label = term.get_text(" ", strip=True).rstrip(":")
            value = value_node.get_text(" ", strip=True)

            if label and value:
                features.setdefault(label, value)

    # List-item parameter layouts.
    for item in soup.select(
        '[data-testid="ad-parameters"] li, '
        '[data-testid="ad-parameters-container"] li'
    ):
        text = item.get_text(" ", strip=True)

        if ":" not in text:
            continue

        label, value = text.split(":", 1)
        label = label.strip().rstrip(":")
        value = value.strip()

        if label and value:
            features.setdefault(label, value)

    return features


def extract_detail_page(url):
    html = get_page(url)

    if html is None:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    features = extract_detail_features(soup)

    title_node = soup.select_one('h1[data-cy="ad_title"], h1')

    if title_node:
        features.setdefault("Detail page title", clean_text(title_node))

    price_node = soup.select_one(
        '[data-testid="ad-price-container"] h3, '
        '[data-testid="ad-price"]'
    )

    if price_node:
        features.setdefault("Detail page price", clean_text(price_node))

    # Description intentionally omitted.
    return features


# ============================================================
# JSONL AND CSV
# ============================================================

def append_jsonl(records):
    if not records:
        return

    with JSONL_FILE.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def convert_jsonl_to_csv():
    if not JSONL_FILE.exists():
        log("No JSONL file found; CSV was not created.")
        return

    fieldnames = []
    seen_fields = set()
    record_count = 0

    # First pass: discover all column names.
    with JSONL_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            record_count += 1

            for field in record:
                if field not in seen_fields:
                    seen_fields.add(field)
                    fieldnames.append(field)

    if not fieldnames:
        log("No valid records available for CSV export.")
        return

    # Second pass: write CSV.
    with JSONL_FILE.open("r", encoding="utf-8") as source, \
            CSV_FILE.open(
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as target:

        writer = csv.DictWriter(
            target,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()

        for line in source:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            writer.writerow(record)

    log(
        f"CSV created: {CSV_FILE}"
        f" | Records: {record_count:,}"
        f" | Columns: {len(fieldnames):,}"
    )


# ============================================================
# MAIN SCRAPER
# ============================================================

def main():
    log("=" * 70)
    log("OLX CAR SCRAPER")
    log("=" * 70)
    log(
        f"Target: {TOTAL_TARGET:,}"
        f" | Years: {YEAR_START}-{YEAR_END}"
        f" | Body types: {len(BODY_TYPES)}"
        f" | Fuel types: {len(FUEL_TYPES)}"
        f" | Workers: {MAX_WORKERS}"
    )

    # Step 1: Load or calculate preliminary counts.
    counts = discover_all_counts()

    if not counts:
        log("No preliminary counts available. Nothing to scrape.")
        return

    total_estimated = sum(counts.values())

    log(f"Estimated matching listings: {total_estimated:,}")

    if total_estimated <= 0:
        log("All preliminary counts are zero. Stopping.")
        return

    # Step 2: Allocate targets proportionally.
    targets = allocate_targets(TOTAL_TARGET, counts)
    allocated_target = sum(targets.values())

    log(f"Allocated target: {allocated_target:,}")

    if allocated_target <= 0:
        log("No targets allocated. Nothing to scrape.")
        return

    # Step 3: Start a fresh dataset, preserving the count cache.
    if JSONL_FILE.exists():
        JSONL_FILE.unlink()

    pending_records = []
    globally_seen = set()

    total_saved = 0
    detail_errors = 0
    total_combo_count = 0

    # Group combinations by BODY TYPE, then FUEL TYPE, then YEAR.
    # This replaces the previous largest-target-first sorting.
    groups = []

    for body_name, body_value in BODY_TYPES.items():
        for fuel_name, fuel_value in FUEL_TYPES.items():
            year_combinations = []

            for year in range(YEAR_START, YEAR_END + 1):
                key = combo_key(body_value, fuel_value, year)

                if key not in counts:
                    continue

                target = targets.get(key, 0)

                if target <= 0:
                    continue

                year_combinations.append((
                    key,
                    body_name,
                    body_value,
                    fuel_name,
                    fuel_value,
                    year,
                    target,
                ))

            if year_combinations:
                groups.append((
                    body_name,
                    fuel_name,
                    year_combinations,
                ))

    total_combo_count = sum(
        len(year_combinations)
        for _, _, year_combinations in groups
    )

    completed_combinations = 0

    log(
        f"Scraping {total_combo_count:,} allocated year-combinations "
        f"across {len(groups):,} body/fuel groups."
    )

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

            for group_index, (
                body_name,
                fuel_name,
                year_combinations,
            ) in enumerate(groups, start=1):

                if total_saved >= TOTAL_TARGET:
                    break

                group_start_saved = total_saved
                group_start_combinations = completed_combinations

                for (
                    key,
                    _,
                    body_value,
                    _,
                    fuel_value,
                    year,
                    target,
                ) in year_combinations:

                    if total_saved >= TOTAL_TARGET:
                        break

                    collected = 0
                    page = 1
                    empty_pages = 0

                    while (
                        collected < target
                        and page <= MAX_PAGES_PER_SEARCH
                        and total_saved < TOTAL_TARGET
                    ):
                        search_url = build_search_url(
                            body_value=body_value,
                            fuel_value=fuel_value,
                            year=year,
                            page=page,
                        )

                        html = get_page(
                            search_url,
                            expected_search=True,
                        )

                        if html is None:
                            log(
                                f"Could not load {body_name} / "
                                f"{fuel_name} / {year}, page {page}."
                            )
                            break

                        listings = extract_listing_cards(html)

                        if not listings:
                            empty_pages += 1

                            if empty_pages >= 2:
                                break

                            page += 1
                            continue

                        empty_pages = 0
                        new_listings = []

                        for listing in listings:
                            url = listing["URL"]

                            if url in globally_seen:
                                continue

                            globally_seen.add(url)
                            new_listings.append(listing)

                        if not new_listings:
                            status(
                                f"{body_name} | {fuel_name} | {year}"
                                f" | Page {page} | No new URLs"
                                f" | Total: {total_saved}/{TOTAL_TARGET}"
                            )
                            page += 1
                            continue

                        futures = {
                            executor.submit(
                                extract_detail_page,
                                listing["URL"],
                            ): listing
                            for listing in new_listings
                        }

                        for future in as_completed(futures):
                            listing = futures[future]

                            try:
                                detail = future.result()
                            except Exception:
                                detail = {}
                                detail_errors += 1

                            record = dict(listing)
                            record.update(detail)

                            record["Search body type"] = body_name
                            record["Search fuel type"] = fuel_name
                            record["Search year"] = year

                            pending_records.append(record)
                            collected += 1
                            total_saved += 1

                            # Save in batches, then flush remaining
                            # records at the end of each year-combination.
                            if len(pending_records) >= SAVE_BATCH_SIZE:
                                append_jsonl(pending_records)
                                pending_records.clear()

                            status(
                                f"{body_name} | {fuel_name} | {year}"
                                f" | Page {page}"
                                f" | Year: {collected}/{target}"
                                f" | Group: {group_index}/{len(groups)}"
                                f" | Total: {total_saved}/{TOTAL_TARGET}"
                            )

                            if (
                                collected >= target
                                or total_saved >= TOTAL_TARGET
                            ):
                                break

                        page += 1

                    # Flush at every year-combination, even when the
                    # configured batch size has not yet been reached.
                    if pending_records:
                        append_jsonl(pending_records)
                        pending_records.clear()

                    completed_combinations += 1

                group_saved = total_saved - group_start_saved
                group_combinations = (
                    completed_combinations - group_start_combinations
                )

                log(
                    f"Completed {body_name} | {fuel_name}: "
                    f"{group_saved:,} cars across "
                    f"{group_combinations:,} year-combinations"
                    f" | Total: {total_saved:,}/{TOTAL_TARGET:,}"
                )

    except KeyboardInterrupt:
        # Preserve any records not yet written to disk.
        if pending_records:
            append_jsonl(pending_records)
            pending_records.clear()

        log("Interrupted by user.")
        log("Completed count estimates remain cached.")
        log("Collected JSONL records have been saved.")

        if JSONL_FILE.exists():
            convert_jsonl_to_csv()

        return

    # Final flush.
    if pending_records:
        append_jsonl(pending_records)
        pending_records.clear()

    log("=" * 70)
    log("SCRAPING FINISHED")
    log("=" * 70)
    log(f"Total records saved: {total_saved:,}")
    log(f"JSONL file: {JSONL_FILE}")
    log(f"Counts cache: {COUNTS_CACHE_FILE}")
    log(f"Detail-page errors: {detail_errors:,}")

    convert_jsonl_to_csv()


if __name__ == "__main__":
    main()