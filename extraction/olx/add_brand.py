
import pandas as pd
import re, unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
OLX_DATA_DIR = REPO_ROOT / "data" / "olx"
AUTOVIT_DATA_DIR = REPO_ROOT / "data" / "autovit"

olx_path = OLX_DATA_DIR / "cars.csv"
autovit_path = AUTOVIT_DATA_DIR / "autovit_cars.csv"
output_path = OLX_DATA_DIR / "cars_with_brands.csv"

olx, autovit = pd.read_csv(olx_path), pd.read_csv(autovit_path)

def norm(s):
    return ''.join(c for c in unicodedata.normalize("NFKD", str(s).casefold().strip()) if not unicodedata.combining(c))

brands = sorted({b.strip() for b in autovit["Marca"].dropna().astype(str) if b.strip()}, key=len, reverse=True)

def canonical(target):
    n = norm(target)
    return next((b for b in brands if norm(b) == n or (n in {"mercedes", "mercedes benz"} and "mercedes" in norm(b)) or (n == "ds" and norm(b).startswith("ds"))), target)

aliases = {
    r"\b(?:vw|ww|vv|v\.w\.|wozvagan|volswagen|wolksvagen|volskwagen|glof|pasat|past|saran)\b": "Volkswagen",
    r"\b(?:pegeot|pejot|pejou|peugeout|pegeout)\b": "Peugeot",
    r"\b(?:mercedes|mercedess|mercedez|mersedes|merceds|mercedrs|mercesese|mercedesc|mercede|mercedes-benz)\b": "Mercedes-Benz",
    r"\b(?:bmw|b\s*m\s*w)\b": "BMW",
    r"\bchevrolett\b": "Chevrolet",
    r"\bnisan\b": "Nissan",
    r"\bminicooper\b": "MINI",
    r"\brange\s+rover\b": "Land Rover",
    r"\bfiat(?=\s*\d)": "Fiat",
    r"\bds\s*3\s+automobiles\b": "DS Automobiles",
    r"\bscoda\b": "Skoda",
    r"\b(?:hiunday|hyunday)\b": "Hyundai",
    r"\b(?:mitshubishi|mitsubi)\b": "Mitsubishi",
    r"\bopal\b": "Opel",
    r"\brenou\b": "Renault",
    r"\btoyoya\b": "Toyota",
    r"\baud\b": "Audi"
}

title_models = {
    r"\b(?:golf\s*4?|bora|passat|polo|sharan|tiguan|touran|jetta|fox|caddy|arteon|beetle|id\.?\s*5)\b": "Volkswagen",
    r"\b(?:e36|e39|e46|e60|e87|e90|e91|e92|f30|seria\s*[35]|m3|i3|i5)\b": "BMW",
    r"\b(?:w205|w220|w210|w208|clk\s*\d{3}|slk|slc\s*\d{3}|sl\s*\d{2,3}|sprinter|vito|citan|cla\s*45|sl\s*63|a\s*250|e\s*class|ml\s*(?:w163|w164|w166|\d{3}))\b": "Mercedes-Benz",
    r"\b(?:logan|solenza|sandero)\b": "Dacia",
    r"\b(?:fabia|rapid)\b": "Skoda",
    r"\b(?:micra|primera)\b": "Nissan",
    r"\bsirion\b": "Daihatsu",
    r"\b(?:matiz|cielo|nubira)\b": "Daewoo",
    r"\b(?:clio|clioo|megane|laguna|talisman|kangoo|symbol)\b": "Renault",
    r"\bmx-5\b|\bmazda\s*3\b": "Mazda",
    r"\bmini\s+cooper\b": "MINI",
    r"\b(?:a\s*7|a\s*6|a\s*4)\b": "Audi",
    r"\b(?:i10|i30|elantra)\b": "Hyundai",
    r"\b(?:wrx\s*sti|sti\s+wrx)\b": "Subaru",
    r"\bghost\b": "Rolls-Royce",
    r"\b508\b": "Peugeot",
    r"\bfocus\b": "Ford",
    r"\bcorolla\b": "Toyota",
    r"\b(?:pajero|l200)\b": "Mitsubishi",
    r"\b(?:vectra|corsa|meriva|astra|insignia)\b": "Opel",
    r"\bfreelander\b": "Land Rover",
    r"\b(?:c3|c3\s*picasso)\b": "Citroen",
    r"\b(?:aveo|kalos)\b": "Chevrolet",
    r"\b(?:207|206)\b": "Peugeot",
    r"\b(?:punto|albea)\b": "Fiat",
    r"\bcivic\b": "Honda",
    r"\boctavia\b": "Skoda",
    r"\bpanamera\b": "Porsche",
    r"\b(?:swift|sx4)\b": "Suzuki"
}

model_brands = {
    "adam": "Opel", "beetle": "Volkswagen", "kalos": "Chevrolet",
    "a4 cabrio": "Audi", "a7 sportback": "Audi", "a7": "Audi",
    "talisman": "Renault", "cla 45 amg": "Mercedes-Benz",
    "i10": "Hyundai", "focus": "Ford", "wrx sti": "Subaru",
    "passat": "Volkswagen", "rapid": "Skoda", "sl 63 amg": "Mercedes-Benz",
    "i30": "Hyundai", "ghost": "Rolls-Royce", "a 250": "Mercedes-Benz",
    "508": "Peugeot", "sandero stepway": "Dacia", "m3": "BMW",
    "elantra": "Hyundai", "corolla": "Toyota", "i5": "BMW",
    "pajero": "Mitsubishi", "a6 limuzina": "Audi", "l200": "Mitsubishi",
    "vectra": "Opel", "ml": "Mercedes-Benz",
    "a4 limuzina": "Audi", "clio": "Renault", "freelander": "Land Rover",
    "e class": "Mercedes-Benz", "id.5": "Volkswagen", "c3": "Citroen",
    "corsa": "Opel", "caddy": "Volkswagen", "seria 5": "BMW",
    "seria 3": "BMW", "tiguan": "Volkswagen", "sandero": "Dacia",
    "laguna": "Renault", "clc 180": "Mercedes-Benz", "i3": "BMW",
    "golf": "Volkswagen", "kangoo": "Renault", "megane": "Renault",
    "nubira": "Daewoo", "207": "Peugeot", "punto": "Fiat",
    "meriva": "Opel", "jetta": "Volkswagen", "civic": "Honda",
    "astra": "Opel", "fox": "Volkswagen", "albea": "Fiat",
    "aveo": "Chevrolet", "206": "Peugeot", "symbol": "Renault",
    "octavia": "Skoda", "touran": "Volkswagen", "insignia": "Opel",
    "passat cc": "Volkswagen", "swift": "Suzuki", "lancer": "Mitsubishi",
    "panamera": "Porsche", "sx4": "Suzuki", "rapid": "Skoda",
    "a7 sportback": "Audi", "sl 63 amg": "Mercedes-Benz",
    "sandero stepway": "Dacia", "a6 limuzina": "Audi",
    "a4 limuzina": "Audi", "wrx sti": "Subaru",
    "seria 5": "BMW", "seria 3": "BMW"
}

def extract_title(title):
    if pd.isna(title):
        return None
    title = norm(title)

    for b in brands:
        if re.search(r"(?<!\w)" + re.escape(norm(b)) + r"(?!\w)", title):
            return b

    for patterns in (aliases, title_models):
        for p, target in patterns.items():
            if re.search(p, title):
                return canonical(target)

    return None

olx["title_brand"] = olx["Title"].apply(extract_title)

olx["model_brand"] = olx["Model"].apply(
    lambda m: canonical(model_brands[norm(m)])
    if pd.notna(m) and norm(m) in model_brands else None
)

olx["brand_mismatch"] = (
    olx["title_brand"].notna() & olx["model_brand"].notna() &
    (olx["title_brand"].apply(lambda x: norm(x) if pd.notna(x) else "") !=
     olx["model_brand"].apply(lambda x: norm(x) if pd.notna(x) else ""))
)

olx["brand"] = olx["title_brand"].fillna(olx["model_brand"])

matched = olx["brand"].notna().sum()
olx.to_csv(output_path, index=False, encoding="utf-8-sig")

print(f"Brands extracted: {matched}/{len(olx)} ({matched/len(olx):.2%})")
print(f"Title/model mismatches: {olx['brand_mismatch'].sum()}")
print(f"Saved to: {output_path}")