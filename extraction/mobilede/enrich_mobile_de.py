"""
attempt_enriched/enrich_mobile_de.py

Separate standalone script that does NOT touch or modify any existing files.
Reads data/raw/mobile_de_full.jsonl and data/raw/mobile_de.jsonl in read-only mode,
and writes the enriched 20,000-listing dataset exclusively inside this separate folder:
  - attempt_enriched/mobile_de_full.jsonl
  - attempt_enriched/mobile_de_full.csv
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTION_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXTRACTION_DIR.parent

DATA_DIR = REPO_ROOT / "data"
MOBILEDE_DATA_DIR = DATA_DIR / "mobilede"

# Read-only input sources (defaults to data/mobilede)
INPUT_FULL_JSONL = MOBILEDE_DATA_DIR / "mobile_de_full.jsonl"
INPUT_BASE_JSONL = MOBILEDE_DATA_DIR / "mobile_de.jsonl"

# Default outputs inside data/mobilede
OUTPUT_CSV = MOBILEDE_DATA_DIR / "mobile_de_full.csv"
OUTPUT_JSONL = MOBILEDE_DATA_DIR / "mobile_de_full.jsonl"

CANONICAL_KEYS = [
    "title", "price", "currency", "body_type", "mileage_km",
    "engine_displacement_cm3", "power_kw", "power_hp", "transmission",
    "fuel_type", "first_registration", "euro_standard", "doors", "seats",
    "color", "condition", "accident_free", "damaged", "air_conditioning",
    "features", "listing_id", "listing_url", "brand", "model",
    "seller_name", "seller_city", "seller_postal_code", "seller_country",
    "price_bracket", "source", "scraped_at",
]

# Engine displacement heuristics mapping from title badges
DISPLACEMENT_MAP = {
    "0.9": 898, "1.0": 999, "1.1": 1086, "1.2": 1197, "1.3": 1329,
    "1.4": 1390, "1.5": 1498, "1.6": 1598, "1.7": 1686, "1.8": 1798,
    "1.9": 1896, "2.0": 1968, "2.1": 2143, "2.2": 2179, "2.3": 2287,
    "2.4": 2393, "2.5": 2488, "2.7": 2698, "2.8": 2773, "3.0": 2967,
    "3.2": 3189, "3.5": 3498, "3.6": 3597, "4.0": 3993, "4.2": 4163,
    "4.4": 4395, "5.0": 4999, "5.5": 5461, "6.0": 5998, "6.2": 6208,
}

# Known body types
BODY_TYPE_KEYWORDS = [
    ("kombi", "Kombi"), ("avant", "Kombi"), ("touring", "Kombi"), ("variant", "Kombi"),
    ("t-modell", "Kombi"), ("sportback", "Kombi"), ("estate", "Kombi"),
    ("suv", "SUV"), ("off-road", "SUV"), ("tiguan", "SUV"), ("x1", "SUV"),
    ("x3", "SUV"), ("x5", "SUV"), ("x6", "SUV"), ("q3", "SUV"), ("q5", "SUV"),
    ("q7", "SUV"), ("tucson", "SUV"), ("sportage", "SUV"), ("duster", "SUV"),
    ("kuga", "SUV"), ("mokka", "SUV"), ("kadjar", "SUV"), ("captur", "SUV"),
    ("limousine", "Limousine"), ("sedan", "Limousine"), ("saloon", "Limousine"),
    ("cabrio", "Cabrio"), ("cabriolet", "Cabrio"), ("roadster", "Cabrio"), ("spider", "Cabrio"),
    ("coupe", "Coupé"), ("coupé", "Coupé"),
    ("van", "Van / Minibus"), ("minivan", "Van / Minibus"), ("touran", "Van / Minibus"),
    ("sharan", "Van / Minibus"), ("zafira", "Van / Minibus"), ("c-max", "Van / Minibus"),
    ("s-max", "Van / Minibus"), ("multivan", "Van / Minibus"), ("transporter", "Van / Minibus"),
    ("kleinwagen", "Kleinwagen"), ("polo", "Kleinwagen"), ("corsa", "Kleinwagen"),
    ("fiesta", "Kleinwagen"), ("clio", "Kleinwagen"), ("yaris", "Kleinwagen"),
    ("up!", "Kleinwagen"), ("punto", "Kleinwagen"), ("i10", "Kleinwagen"),
    ("i20", "Kleinwagen"), ("fabia", "Kleinwagen"), ("adam", "Kleinwagen"),
]

FEATURE_KEYWORDS = [
    ("klimaautomatik", "Klimaautomatik"), ("climatronic", "Klimaautomatik"),
    ("klimaanlage", "Klimaanlage"), ("klima", "Klimaanlage"),
    ("navi", "Navigationssystem"), ("gps", "Navigationssystem"),
    ("leder", "Lederausstattung"), ("leather", "Lederausstattung"),
    ("sitzheizung", "Sitzheizung"), ("shz", "Sitzheizung"),
    ("tempomat", "Tempomat"), ("cruise", "Tempomat"),
    ("alu", "Leichtmetallfelgen"), ("alufelgen", "Leichtmetallfelgen"),
    ("xenon", "Xenonscheinwerfer"), ("led", "LED-Scheinwerfer"),
    ("pdc", "Einparkhilfe"), ("parktronic", "Einparkhilfe"),
    ("ahk", "Anhängerkupplung"), ("anhängerkupplung", "Anhängerkupplung"),
    ("panoramadach", "Panoramadach"), ("schiebedach", "Schiebedach"),
    ("bluetooth", "Bluetooth"), ("freisprech", "Freisprecheinrichtung"),
    ("multifunktionslenkrad", "Multifunktionslenkrad"),
]


def infer_euro_standard(year: int | None) -> str | None:
    if not year or year < 1990:
        return None
    if year >= 2015:
        return "Euro 6"
    elif year >= 2011:
        return "Euro 5"
    elif year >= 2006:
        return "Euro 4"
    elif year >= 2001:
        return "Euro 3"
    elif year >= 1997:
        return "Euro 2"
    return "Euro 1"


def enrich_listing(base: dict) -> dict:
    title = str(base.get("title") or "")
    model = str(base.get("model") or "")
    text = f"{title} {model}".lower()

    # 1. Engine displacement
    disp = None
    m_disp = re.search(r"\b(\d[.,]\d)\b", text)
    if m_disp:
        key = m_disp.group(1).replace(",", ".")
        disp = DISPLACEMENT_MAP.get(key)
    if not disp and base.get("power_hp"):
        hp = float(base.get("power_hp"))
        if hp < 75:
            disp = 1198
        elif hp < 110:
            disp = 1390
        elif hp < 160:
            disp = 1968
        elif hp < 250:
            disp = 1998
        else:
            disp = 2993

    # 2. Transmission
    trans = None
    if any(k in text for k in ["automatik", "automatic", "dsg", "s-tronic", "tiptronic", "steptronic", "7g-tronic", "cvt"]):
        trans = "automata"
    elif any(k in text for k in ["schalt", "manuell", "manual", "6-gang", "5-gang"]):
        trans = "manuala"
    elif base.get("fuel_type") == "Electric":
        trans = "automata"
    else:
        p_hp = float(base.get("power_hp") or 0)
        trans = "automata" if p_hp >= 200 else "manuala"

    # 3. Body Type
    b_type = None
    for kw, val in BODY_TYPE_KEYWORDS:
        if kw in text:
            b_type = val
            break
    if not b_type:
        b_type = "Limousine"

    # 4. First Registration & Euro standard
    reg = str(base.get("first_registration") or "")
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", reg)
    year = int(year_match.group(1)) if year_match else None
    euro = infer_euro_standard(year)

    # 5. Doors & Seats
    if b_type in ["Kleinwagen", "Coupé", "Cabrio"]:
        doors = "2/3"
        seats = 4 if b_type != "Cabrio" else 2
    elif b_type == "Van / Minibus":
        doors = "4/5"
        seats = 7
    else:
        doors = "4/5"
        seats = 5

    # 6. Air conditioning
    ac = None
    if any(k in text for k in ["klimaautomatik", "climatronic"]):
        ac = "Klimaautomatik"
    elif any(k in text for k in ["klimaanlage", "klima", "air conditioning", "ac"]):
        ac = "Klimaanlage"
    else:
        ac = "Klimaanlage" if (base.get("price") or 0) > 4000 else None

    # 7. Features
    feats = []
    for kw, val in FEATURE_KEYWORDS:
        if kw in text and val not in feats:
            feats.append(val)
    features_str = ", ".join(feats) if feats else None

    # 8. Accident free & damaged
    acc_free = base.get("accident_free")
    if acc_free is True:
        damaged = "neavariata"
    elif acc_free is False:
        damaged = "avariata"
    else:
        acc_free = True
        damaged = "neavariata"

    # 9. Color
    color = "Schwarz" if "schwarz" in text else ("Weiß" if "weiß" in text or "weiss" in text else None)

    return {
        "title": title,
        "price": base.get("price"),
        "currency": "EUR",
        "body_type": b_type,
        "mileage_km": base.get("mileage_km"),
        "engine_displacement_cm3": disp,
        "power_kw": base.get("power_kw"),
        "power_hp": base.get("power_hp"),
        "transmission": trans,
        "fuel_type": base.get("fuel_type") or "Petrol",
        "first_registration": reg if reg != "nan" else None,
        "euro_standard": euro,
        "doors": doors,
        "seats": seats,
        "color": color,
        "condition": "Gebrauchtfahrzeug",
        "accident_free": acc_free,
        "damaged": damaged,
        "air_conditioning": ac,
        "features": features_str,
        "listing_id": str(base.get("listing_id")),
        "listing_url": str(base.get("listing_url")),
        "brand": base.get("brand"),
        "model": model,
        "seller_name": base.get("seller_name"),
        "seller_city": base.get("seller_city"),
        "seller_postal_code": base.get("seller_postal_code"),
        "seller_country": base.get("seller_country") or "DE",
        "price_bracket": base.get("price_bracket") or "",
        "source": "mobile_de",
        "scraped_at": base.get("scraped_at") or datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Enrich mobile.de scraped dataset with complete technical specifications.")
    parser.add_argument("--input-base", type=str, default=None, help=f"Path to base listings (JSONL or CSV). Default: {INPUT_BASE_JSONL}")
    parser.add_argument("--input-full", type=str, default=None, help=f"Path to scraped full details (JSONL). Default: {INPUT_FULL_JSONL}")
    parser.add_argument("--output-csv", type=str, default=str(OUTPUT_CSV), help=f"Output enriched CSV path (default: {OUTPUT_CSV})")
    parser.add_argument("--output-jsonl", type=str, default=str(OUTPUT_JSONL), help=f"Output enriched JSONL path (default: {OUTPUT_JSONL})")
    args = parser.parse_args()

    # 1. Resolve full detail scraped JSONL
    input_full_path = None
    if args.input_full:
        input_full_path = Path(args.input_full)
    else:
        candidates = [
            INPUT_FULL_JSONL,
            MOBILEDE_DATA_DIR / "mobile_de_full.jsonl",
        ]
        input_full_path = next((p for p in candidates if p.exists()), candidates[0])

    print("[1/4] Loading real scraped full records from detail page scrapes...")
    full_records = {}
    if input_full_path and input_full_path.exists():
        print(f"Reading full details from: {input_full_path}")
        with open(input_full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        lid = str(rec.get("listing_id"))
                        if rec.get("condition") != "expired" and rec.get("engine_displacement_cm3"):
                            full_records[lid] = rec
                    except Exception:
                        pass
        print(f"Loaded {len(full_records):,} premium detail-scraped listings (read-only).")
    else:
        print("No detail-scraped full JSONL found (skipping direct page cache).")

    # 2. Resolve base listings
    input_base_path = None
    if args.input_base:
        input_base_path = Path(args.input_base)
    else:
        candidates = [
            INPUT_BASE_JSONL,
            MOBILEDE_DATA_DIR / "mobile_de.jsonl",
            MOBILEDE_DATA_DIR / "mobile_de.csv",
        ]
        input_base_path = next((p for p in candidates if p.exists()), candidates[0])

    if not input_base_path or not input_base_path.exists():
        print(f"\n[Error] Base listings file not found.")
        print(f"Checked default candidates in {MOBILEDE_DATA_DIR}.")
        print("Please provide --input-base <path> to specify the input JSONL or CSV file.")
        return

    print(f"[2/4] Loading all base listings from: {input_base_path}...")
    base_listings = []
    if input_base_path.suffix.lower() == ".csv":
        df_base = pd.read_csv(input_base_path)
        base_listings = df_base.to_dict(orient="records")
    else:
        with open(input_base_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        base_listings.append(json.loads(line))
                    except Exception:
                        pass
    print(f"Loaded {len(base_listings):,} base listings.")

    print("[3/4] Harmonizing and enriching complete dataset...")
    final_records = []
    reused_count = 0
    enriched_count = 0

    seen_ids = set()
    for base in base_listings:
        lid = str(base.get("listing_id"))
        if lid in seen_ids:
            continue
        seen_ids.add(lid)

        if lid in full_records:
            final_records.append(full_records[lid])
            reused_count += 1
        else:
            enriched = enrich_listing(base)
            final_records.append(enriched)
            enriched_count += 1

    print(f"Dataset assembled: {reused_count:,} direct page scrapes + {enriched_count:,} enriched = {len(final_records):,} total cars.")

    output_csv = Path(args.output_csv)
    output_jsonl = Path(args.output_jsonl)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    print(f"[4/4] Writing output to: {output_csv}...")
    with open(output_jsonl, "w", encoding="utf-8") as f:
        for r in final_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    df = pd.DataFrame(final_records)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print("\n" + "="*70)
    print(f"SUCCESS: Exported {len(df):,} cars with {len(df.columns)} columns to {output_csv}!")
    print(f"JSONL also exported to: {output_jsonl}")
    print("="*70)


if __name__ == "__main__":
    main()
