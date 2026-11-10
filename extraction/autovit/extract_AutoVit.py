
import csv
import json
import math
import os
import re
import time
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURATION
# ============================================================

TARGET_TOTAL = 20_000
SAVE_BATCH_SIZE = 500
DELAY = 0.1

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
AUTOVIT_DATA_DIR = REPO_ROOT / "data" / "autovit"
AUTOVIT_DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.autovit.ro"
OUTPUT_FILE = str(AUTOVIT_DATA_DIR / "autovit_cars.csv")
TEMP_FILE = OUTPUT_FILE + ".tmp"

# Add or remove body types here. Counts are discovered automatically.
BODY_TYPES = {
    "SUV": "/autoturisme/seg-suv",
    "Sedan": "/autoturisme/seg-sedan",
    "Combi": "/autoturisme/seg-combi",
    "Compacta": "/autoturisme/seg-compact",
    "Monovolum": "/autoturisme/seg-monovolum",
    "Masina de oras": "/autoturisme/seg-masina-de-oras",
    "Masina mica": "/autoturisme/seg-masina-mica",
    "Coupe": "/autoturisme/seg-coupe",
    "Cabrio": "/autoturisme/seg-cabrio",
}

# Only the requested detail fields are collected.
ALLOWED_DETAIL_LABELS = [
    "Marca",
    "Model",
    "Versiune",
    "Culoare",
    "Numar de portiere",
    "Numar locuri",
    "Anul productiei",
    "Data primei inmatriculari",
    "Combustibil",
    "Capacitate cilindrica",
    "Putere",
    "Tip Caroserie",
    "Optiuni culoare",
    "Cutie de viteze",
    "Transmisie",
    "Emisii CO2",
    "Consum Urban",
    "Consum Extraurban",
    "Norma de poluare",
    "Tara de origine",
    "Km",
    "Garantie dealer (inclusa in pret)",
    "Stare",
    "Inmatriculat",
    "Fara accident in istoric",
    "Carte de service",
    "Tuning",
]

def normalize_text(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", value).strip().lower()


ALLOWED_LABELS_NORMALIZED = {
    normalize_text(label): label
    for label in ALLOWED_DETAIL_LABELS
}


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
})

retry = Retry(
    total=4,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)


def get_page(url):
    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()
        time.sleep(DELAY)
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as error:
        print(f"\nRequest failed: {url}\n{error}")
        return None


# ============================================================
# AUTOMATIC BODY-TYPE COUNT DISCOVERY
# ============================================================

def discover_body_type_counts():
    """
    Read category counts from the Autovit category page.

    This uses the page's visible text and is best-effort:
    verify the printed counts before a long run.
    """
    soup = get_page(f"{BASE_URL}/autoturisme/anunt")

    if soup is None:
        raise RuntimeError("Could not load the category page.")

    counts = {}

    # Prefer category links, because their text is more likely to
    # contain the relevant category name and its count together.
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        link_text = link.get_text(" ", strip=True)

        for name, path in BODY_TYPES.items():
            if path.rstrip("/") not in href.split("?")[0].rstrip("/"):
                continue

            match = re.search(
                r"([\d][\d\s.,]*)\s*$",
                link_text,
            )

            if match:
                digits = re.sub(r"\D", "", match.group(1))
                if digits:
                    counts[name] = int(digits)

    # Fallback: search the full page text if category-link text
    # did not expose a count for a particular category.
    page_text = soup.get_text(" ", strip=True)

    for name in BODY_TYPES:
        if name in counts:
            continue

        pattern = (
            r"(?<!\w)"
            + re.escape(name)
            + r"(?!\w)\s*[\(\[]?\s*([\d][\d\s.,]*)"
        )

        match = re.search(pattern, page_text, re.IGNORECASE)

        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                counts[name] = int(digits)

    missing = [name for name in BODY_TYPES if name not in counts]

    print("\nDiscovered category counts:")
    for name in BODY_TYPES:
        value = counts.get(name)
        print(f"  {name:<20} {value if value is not None else 'NOT FOUND'}")

    if missing:
        raise RuntimeError(
            "Could not reliably discover counts for: "
            + ", ".join(missing)
            + ". Inspect the category page HTML and adjust "
              "discover_body_type_counts() before scraping."
        )

    return counts


def calculate_targets(counts, total):
    """Allocate the requested sample proportionally."""
    count_sum = sum(counts.values())

    if count_sum <= 0:
        raise ValueError("Category counts are invalid.")

    exact = {
        name: total * count / count_sum
        for name, count in counts.items()
    }

    targets = {
        name: math.floor(value)
        for name, value in exact.items()
    }

    remaining = total - sum(targets.values())

    ranked = sorted(
        counts,
        key=lambda name: exact[name] - targets[name],
        reverse=True,
    )

    for name in ranked[:remaining]:
        targets[name] += 1

    return targets


# ============================================================
# LISTING-PAGE EXTRACTION
# ============================================================

def find_listing_cards(soup):
    cards = soup.select('[data-testid="listing-item"]')

    if not cards:
        cards = soup.select("article")

    return cards


def get_card_url(card):
    for link in card.select("a[href]"):
        href = link.get("href", "")

        if "/anunt/" in href or "/oferta/" in href:
            return urljoin(BASE_URL, href)

    for link in card.select("a[href]"):
        href = link.get("href", "")

        if "/autoturisme/" in href:
            return urljoin(BASE_URL, href)

    return None


def extract_listing_record(card, body_type):
    url = get_card_url(card)

    if not url:
        return None

    title = ""
    for selector in (
        '[data-testid="ad-card-title"]',
        "h2",
        "h3",
    ):
        element = card.select_one(selector)
        if element:
            title = element.get_text(" ", strip=True)
            if title:
                break

    text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))

    price = ""
    price_element = (
        card.select_one('[data-testid="ad-price"]')
        or card.select_one('[data-testid*="price"]')
    )

    if price_element:
        price = price_element.get_text(" ", strip=True)
    else:
        match = re.search(
            r"\d[\d\s.,]*\s*(?:€|EUR|lei|RON)",
            text,
            re.IGNORECASE,
        )
        if match:
            price = match.group(0).strip()

    mileage = ""
    match = re.search(r"\b\d[\d\s.]*\s*km\b", text, re.IGNORECASE)
    if match:
        mileage = match.group(0).strip()

    year = ""
    match = re.search(r"\b(?:19[8-9]\d|20[0-2]\d|2030)\b", text)
    if match:
        year = match.group(0)

    fuel_type = ""
    fuel_options = [
        "Plug-in Hybrid",
        "Benzina + GPL",
        "Benzina",
        "Diesel",
        "Hibrid",
        "Electrică",
        "Electric",
        "GPL",
        "Hidrogen",
    ]

    normalized_text = normalize_text(text)
    for fuel in fuel_options:
        if normalize_text(fuel) in normalized_text:
            fuel_type = fuel
            break

    id_match = re.search(r"/(?:anunt|oferta)/([^/?#]+)", url)
    listing_id = id_match.group(1) if id_match else url

    return {
        "listing_id": listing_id,
        "body_type": body_type,
        "title": title,
        "url": url,
        "listing_mileage": mileage,
        "listing_fuel_type": fuel_type,
        "listing_year": year,
        "price": price,
    }


# ============================================================
# DETAIL-PAGE EXTRACTION
# ============================================================

def extract_detail_fields(soup):
    details = {}

    excluded_terms = (
        "financing",
        "finance",
        "entrypoint",
        "history",
        "description",
        "equipment",
    )

    for element in soup.select("[data-testid]"):
        test_id = normalize_text(element.get("data-testid", ""))

        if any(term in test_id for term in excluded_terms):
            continue

        # Skip parent containers containing other data-testid elements.
        if element.select("[data-testid]"):
            continue

        paragraphs = element.find_all("p")

        if len(paragraphs) < 2:
            continue

        label = paragraphs[0].get_text(" ", strip=True)
        value = paragraphs[1].get_text(" ", strip=True)

        if not label or not value:
            continue

        normalized_label = normalize_text(label)

        if normalized_label not in ALLOWED_LABELS_NORMALIZED:
            continue

        canonical_label = ALLOWED_LABELS_NORMALIZED[normalized_label]

        if canonical_label not in details:
            details[canonical_label] = value

    return details


def scrape_car_details(url):
    soup = get_page(url)

    if soup is None:
        return {}

    return extract_detail_fields(soup)


# ============================================================
# BATCH SAVING
# ============================================================

def save_batch(temp_file, batch):
    for record in batch:
        temp_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    temp_file.flush()
    batch.clear()


# ============================================================
# FINAL CSV
# ============================================================

def create_final_csv(temp_path, output_path):
    records = []
    discovered_details = set()

    with open(temp_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue

            record = json.loads(line)
            records.append(record)

            discovered_details.update(
                key for key in record
                if key in ALLOWED_DETAIL_LABELS
            )

    listing_columns = [
        "listing_id",
        "body_type",
        "title",
        "url",
        "listing_mileage",
        "listing_fuel_type",
        "listing_year",
        "price",
    ]

    detail_columns = [
        label for label in ALLOWED_DETAIL_LABELS
        if label in discovered_details
    ]

    fieldnames = listing_columns + detail_columns

    with open(
        output_path,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(records)

    print(f"\nCSV created: {output_path}")
    print(f"Records saved: {len(records):,}")
    print(f"Detail columns discovered: {len(detail_columns)}")


# ============================================================
# MAIN
# ============================================================

def main():
    counts = discover_body_type_counts()
    targets = calculate_targets(counts, TARGET_TOTAL)

    print("\nProportional scraping targets:")
    for name in BODY_TYPES:
        print(f"  {name:<20} {targets[name]:,}")

    print(f"  {'TOTAL':<20} {sum(targets.values()):,}")

    batch = []
    seen_urls = set()
    total_saved = 0

    # Start a new temporary file. The previous final CSV is not
    # deleted until a new CSV has been generated successfully.
    try:
        with open(TEMP_FILE, "w", encoding="utf-8") as temp_file:
            for body_type, path in BODY_TYPES.items():
                target = targets[body_type]
                base_url = urljoin(BASE_URL, path)

                category_saved = 0
                page_number = 1

                print(f"\nScraping {body_type}: target {target:,}")

                while category_saved < target:
                    page_url = (
                        base_url
                        if page_number == 1
                        else f"{base_url}?page={page_number}"
                    )

                    soup = get_page(page_url)

                    if soup is None:
                        print(f"\nCould not load page {page_number}.")
                        break

                    cards = find_listing_cards(soup)

                    if not cards:
                        print(f"\nNo listing cards on page {page_number}.")
                        break

                    new_listings = 0

                    for card in cards:
                        if category_saved >= target:
                            break

                        listing = extract_listing_record(card, body_type)

                        if not listing:
                            continue

                        url = listing["url"]
                        if url in seen_urls:
                            continue

                        seen_urls.add(url)
                        new_listings += 1

                        details = scrape_car_details(url)
                        record = {**listing, **details}

                        batch.append(record)
                        category_saved += 1
                        total_saved += 1

                        if len(batch) >= SAVE_BATCH_SIZE:
                            save_batch(temp_file, batch)

                        print(
                            f"\r{body_type}: {category_saved:,}/{target:,} "
                            f"| Total: {total_saved:,}",
                            end="",
                            flush=True,
                        )

                    if new_listings == 0:
                        print(
                            f"\nNo new listings on page {page_number}; "
                            "stopping this category."
                        )
                        break

                    page_number += 1

                print(
                    f"\nFinished {body_type}: "
                    f"{category_saved:,}/{target:,}"
                )

            if batch:
                save_batch(temp_file, batch)

        create_final_csv(TEMP_FILE, OUTPUT_FILE)
        os.remove(TEMP_FILE)

    except KeyboardInterrupt:
        print("\n\nScraping interrupted.")

        if batch:
            try:
                with open(TEMP_FILE, "a", encoding="utf-8") as temp_file:
                    save_batch(temp_file, batch)
            except OSError as error:
                print(f"Could not save remaining batch: {error}")

        print(f"Saved batches are in {TEMP_FILE}.")
        print("The final CSV was not rebuilt.")

    except Exception as error:
        print(f"\nUnexpected error: {error}")
        print(f"Temporary data, if any, remains in {TEMP_FILE}.")
        raise


if __name__ == "__main__":
    main()
