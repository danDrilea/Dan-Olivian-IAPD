"""
Script pentru procesarea si separarea coloanei 'brand' in Marca (brand) si Model (model),
eliminand vechea coloana 'model' (care continea subtitlul anuntului).

Exemple de procesare:
- 'Volkswagen Golf'        -> brand: 'Volkswagen',    model: 'Golf'
- 'Mercedes-Benz C 63 AMG' -> brand: 'Mercedes-Benz', model: 'C 63 AMG'
- 'Alfa Romeo Stelvio'     -> brand: 'Alfa Romeo',    model: 'Stelvio'
- 'Land Rover Defender'    -> brand: 'Land Rover',    model: 'Defender'
- 'BMW X5'                 -> brand: 'BMW',           model: 'X5'
"""

import os
import argparse
import pandas as pd

# Marci compuse (din 2 sau mai multe cuvinte) pentru identificare precisa
MULTIWORD_BRANDS = [
    'Alfa Romeo',
    'Aston Martin',
    'DS Automobiles',
    'Land Rover',
    'Rolls-Royce',
    'Mercedes-Benz',
]

# Setul complet al tuturor celor 54 de marci intalnite in dataset
ALL_KNOWN_BRANDS = {
    'ALPINA', 'Abarth', 'Alfa Romeo', 'Aston Martin', 'Audi', 'BMW', 'Bentley',
    'Cadillac', 'Chevrolet', 'Chrysler', 'Citroën', 'Corvette', 'Cupra',
    'DS Automobiles', 'Dacia', 'Daihatsu', 'Dodge', 'Fiat', 'Ford', 'GMC',
    'Honda', 'Hyundai', 'Iveco', 'Jaguar', 'Jeep', 'Kia', 'Lada', 'Lancia',
    'Land Rover', 'Lexus', 'Lotus', 'MINI', 'Maserati', 'Maybach', 'Mazda',
    'Mercedes-Benz', 'Mitsubishi', 'Morgan', 'Nissan', 'Opel', 'Peugeot',
    'Porsche', 'Renault', 'Rolls-Royce', 'Seat', 'Skoda', 'Smart', 'Ssangyong',
    'Subaru', 'Suzuki', 'Tesla', 'Toyota', 'Volkswagen', 'Volvo'
}

def split_brand_field(val: str) -> tuple[str, str]:
    """
    Imparte textul din coloana 'brand' in:
    - marca (brand)
    - model (model)
    """
    if not isinstance(val, str) or not val.strip():
        return '', ''
    
    text = val.strip()

    # Daca valoarea este deja doar numele marcii (fara model atasat)
    if text in ALL_KNOWN_BRANDS:
        return text, ''

    # Verificare marci compuse
    for mb in MULTIWORD_BRANDS:
        if text.startswith(mb + ' '):
            return mb, text[len(mb):].strip()
        elif text == mb:
            return mb, ''

    # Marci dintr-un singur cuvant (ex: 'Volkswagen Golf' -> 'Volkswagen', 'Golf')
    parts = text.split(' ', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ''

def process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina vechiul 'model' si populeaza brand si model din campul 'brand'."""
    df_out = df.copy()

    # Verificam daca 'brand' contine deja doar marca (fara model)
    sample_brands = df_out['brand'].dropna().head(50)
    already_split = all(b in ALL_KNOWN_BRANDS for b in sample_brands)
    if already_split and 'model' in df_out.columns and df_out['model'].dropna().nunique() > 10:
        print("[INFO] Coloana 'brand' si coloana 'model' sunt deja separate corect!")
        return df_out

    # 1. Extragere marca si model nou
    print("Separare 'brand' in Marca si Model...")
    splits = [split_brand_field(v) for v in df_out['brand']]
    new_brands, new_models = zip(*splits)

    # 2. Inlocuire 'model' si 'brand'
    df_out['brand'] = new_brands
    df_out['model'] = new_models

    return df_out

def main():
    from pathlib import Path
    default_csv = Path(__file__).resolve().parents[2] / "data" / "mobilede" / "mobile_de_ro.csv"

    parser = argparse.ArgumentParser(description="Separa coloana 'brand' in marca si model, eliminand vechiul 'model'.")
    parser.add_argument("--input", default=str(default_csv), help="Calea catre fisierul CSV de intrare")
    parser.add_argument("--output", default=str(default_csv), help="Calea catre fisierul CSV de iesire")

    args = parser.parse_args()
    input_path = os.path.normpath(args.input)
    output_path = os.path.normpath(args.output)

    if not os.path.exists(input_path):
        print(f"Eroare: Fisierul '{input_path}' nu exista!")
        return

    print(f"Incarcare: {input_path}")
    df = pd.read_csv(input_path, low_memory=False)
    print(f"Date incarcate cu succes: {len(df)} randuri, {len(df.columns)} coloane.")

    df_processed = process_dataframe(df)

    print("\nStatistici dupa separare:")
    print(f"- Marci unice identificate: {df_processed['brand'].nunique()}")
    print(f"- Modele unice identificate: {df_processed['model'].nunique()}")
    print("\nTop 10 marci:")
    print(df_processed['brand'].value_counts().head(10).to_string())
    print("\nTop 10 modele:")
    print(df_processed['model'].value_counts().head(10).to_string())

    print(f"\nSalvare in: {output_path}")
    df_processed.to_csv(output_path, index=False)
    print("Succes! Fisierul a fost actualizat.")

if __name__ == "__main__":
    main()
