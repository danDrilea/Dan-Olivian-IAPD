import pandas as pd
from pathlib import Path

# File paths
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
AUTOVIT_DATA_DIR = REPO_ROOT / "data" / "autovit"

input_path = AUTOVIT_DATA_DIR / "autovit_cars.csv"
output_path = AUTOVIT_DATA_DIR / "autovit_prices_cleand.csv"

# 1. Load original dataset
autovit = pd.read_csv(input_path)

# 2. Clean price: remove leading production year
autovit["price"] = (
    autovit["price"]
    .astype("string")
    .str.replace(r"^\s*\d{4}\s+", "", regex=True)
)

# 3. Convert numerical columns
numeric_columns = {
    "price": r"[^\d]",
    "listing_year": r"[^\d]",
    "Capacitate cilindrica": r"[^\d]",
    "Putere": r"[^\d]",
    "listing_mileage": r"[^\d]",
    "Numar de portiere": r"[^\d]"
}

for col, pattern in numeric_columns.items():
    if col in autovit.columns:
        autovit[col] = pd.to_numeric(
            autovit[col]
            .astype("string")
            .str.replace(pattern, "", regex=True),
            errors="coerce"
        )

# 4. Clean text columns
for col in autovit.select_dtypes(include=["object", "string"]).columns:
    autovit[col] = autovit[col].astype("string").str.strip()

# 5. Save cleaned dataset
autovit.to_csv(output_path, index=False, encoding="utf-8-sig")

# 6. Inspect results
print("Original shape:", pd.read_csv(input_path).shape)
print("Cleaned shape:", autovit.shape)
print("Saved to:", output_path)