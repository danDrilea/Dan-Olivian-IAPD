# Predictie Preturi Automobile Second-Hand
**Ingineria si Arhitectura Platformelor de Date (IAPD)**  
**Autori:** Drilea Dan-Alexandru & Ghita-Margescu Olivian

---

## 📁 Structura Repository-ului

Conform specificatiilor de proiect, repository-ul este organizat in 3 module principale:

```text
Dan-Olivian-Repo/
├── extraction/                     # Scripturi de crawling, scraping si preprocesare
│   ├── base_scraper.py             # Motor de baza pentru scraping stealth (Camoufox/Playwright)
│   ├── autovit/                    # AutoVit: crawling si curatare preturi
│   │   ├── extract_AutoVit.py      # Crawler AutoVit (Requests + BeautifulSoup)
│   │   └── clean_price.py          # Script de curatare preturi si coloane numerice
│   ├── olx/                        # OLX: crawling si extragere marci
│   │   ├── extract_OLX.py          # Crawler OLX (curl_cffi + BeautifulSoup)
│   │   └── add_brand.py            # Mapare si extragere marca din titlu/descriere
│   ├── bestauto/                   # BestAuto: crawling si deduplicare
│   │   └── bestauto_scraper.py     # Crawler BestAuto.ro cu hotswap si checkpointing
│   ├── mobilede/                   # Mobile.de: crawling, imbogatire si traducere
│   │   ├── mobile_de_scraper.py    # Crawler carduri mobile.de pe paliere de pret
│   │   ├── mobile_de_full_scraper.py # Crawler specificatii complete detaliate
│   │   ├── enrich_mobile_de.py     # Imbogatire dataset cu specificatii tehnice
│   │   ├── translate_mobile_de.py  # Traducere si normalizare germana -> romana
│   │   └── split_brand_model.py    # Separare atomica coloana Brand in Marca si Model
│   └── Faza_1.ipynb                # Jupyter Notebook: pipeline centralizator, curatare, EDA
├── data/                           # Dataset-uri brute, intermediare si finale
│   ├── autovit/                    # Date AutoVit (brut + preturi curatate)
│   │   ├── autovit_cars.csv
│   │   └── autovit_prices_cleand.csv
│   ├── olx/                        # Date OLX (brut, cache, cu marci extrase)
│   │   ├── cars.csv
│   │   ├── cars_with_brands.csv
│   │   ├── cars.jsonl
│   │   └── counts_cache.json
│   ├── bestauto/                   # Date BestAuto (brut, jsonl, checkpoint)
│   │   ├── bestauto.csv
│   │   ├── bestauto.jsonl
│   │   └── bestauto_checkpoint.json
│   ├── mobilede/                   # Date Mobile.de (carduri, imbogatit, tradus)
│   │   ├── mobile_de.csv
│   │   ├── mobile_de_full.csv
│   │   ├── mobile_de_ro.csv
│   │   ├── mobile_de.jsonl
│   │   ├── mobile_de_full.jsonl
│   │   ├── mobile_de_checkpoint.json
│   │   └── mobile_de_full_checkpoint.json
│   └── centralized/                # Datasetul final unificat si diagramele de distributie
│       ├── cars_centralized.csv
│       └── distributii_dataset_centralizat.png
└── docs/                           # Prezentari si documentatie de proiect
    └── README.md                   # Placeholder pentru prezentarile finale (PDF / PPTX)
```

---

## 🚗 Surse de Date si Volume Colectate

| Sursa | Tehnologie Scraping | Inregistrari Brute | Caracteristici Principale Extrase |
|---|---|---|---|
| **AutoVit.ro** | Requests + BeautifulSoup | ~18.454 | Marca, Model, Pret, An, Km, Combustibil, Capacitate, Putere, Caroserie |
| **OLX.ro** | curl_cffi + BeautifulSoup | ~26.646 | Marca (dedusa), Model, Pret, An, Rulaj, Caroserie, Combustibil, Transmisie |
| **BestAuto.ro** | Requests + BeautifulSoup | ~24.144 | Marca, Model, Pret, An, Km, Putere, Capacitate, Combustibil, Transmisie |
| **Mobile.de** | Camoufox (Stealth Firefox) | ~20.000 | Marca, Model, Pret, An, Km, Specificatii tehnice complete, Dotari, Traduse RO |
| **TOTAL UNIFICAT** | Pipeline `Faza_1.ipynb` | **85.316** | Dataset centralizat curatat, fara duplicate si fara anomalii extreme |

---

## ⚙️ Mod de Rulare a Pipeline-ului

### 1. Instalare dependinte
```bash
pip install -r requirements.txt
```

### 2. Rulare Notebook Centralizator (`Faza_1.ipynb`)
Notebook-ul din `extraction/Faza_1.ipynb` realizeaza:
- Incarcarea automata a celor 4 seturi de date din `../data/`.
- Armonizarea nomenclaturii coloanelor (`brand`, `model`, `price`, `year`, `mileage`, `engine_capacity`, `power`, `fuel_type`, `body_type`, `transmission` etc.).
- Conversia valorilor numerice si tratarea cazurilor particulare (de ex. kilometraj cu zecimale, cilindree BMW 1995 vs an de fabricatie).
- Deduplicarea pe baza de pereche URL/atribute si eliminarea anomaliilor de pret/kilometraj.
- Exportul fisierului final unificat: `data/centralized/cars_centralized.csv`.
- Generarea diagramelor de distributie: `data/centralized/distributii_dataset_centralizat.png`.

