# Predictie Preturi Automobile Second-Hand
**Ingineria si Arhitectura Platformelor de Date (IAPD)**  
**Autori:** Drilea Dan-Alexandru & Ghita-Margescu Olivian

---

## 📁 Structura Repository-ului

Conform specificatiilor de proiect, repository-ul este organizat in 3 module principale:

```text
Dan-Olivian-IAPD/
├── extraction/                     # Scripturi de crawling, scraping si preprocesare
│   ├── base_scraper.py             # Motor de baza pentru scraping stealth (Camoufox/Playwright), checkpoint + JSONL
│   ├── Faza_1_1.ipynb              # Jupyter Notebook: pipeline centralizator, curatare, filtrare, grafice
│   ├── autovit/                    # AutoVit: crawling si curatare preturi
│   │   ├── extract_AutoVit.py      # Crawler AutoVit (Requests + BeautifulSoup) -> autovit_cars.csv
│   │   └── clean_price.py          # Curatare preturi -> autovit_prices_cleand.csv
│   ├── olx/                        # OLX: crawling si extragere marci
│   │   ├── extract_OLX.py          # Crawler OLX (curl_cffi + BeautifulSoup) -> cars.csv / cars.jsonl
│   │   └── add_brand.py            # Deducere marca din titlu/model -> cars_with_brands.csv
│   ├── bestauto/                   # BestAuto: crawling si deduplicare
│   │   └── bestauto_scraper.py     # Crawler BestAuto.ro (Requests + BeautifulSoup) pe paliere de pret, cu checkpointing
│   └── mobilede/                   # Mobile.de: crawling, imbogatire si traducere
│       ├── mobile_de_scraper.py    # Crawler carduri mobile.de pe paliere de pret -> mobile_de.csv
│       ├── mobile_de_full_scraper.py # Crawler pagini de detaliu (specificatii complete)
│       ├── enrich_mobile_de.py     # Detalii scrapuite + estimari euristice pentru restul -> mobile_de_full.csv
│       ├── translate_mobile_de.py  # Traducere si normalizare germana -> romana -> mobile_de_ro.csv
│       └── split_brand_model.py    # Separare coloana brand in Marca si Model (in mobile_de_ro.csv)
├── data/                           # Dataset-uri brute, intermediare si finale
│   ├── autovit/                    # Date AutoVit (brut + preturi curatate)
│   │   ├── autovit_cars.csv
│   │   └── autovit_prices_cleand.csv     # <- folosit in pipeline
│   ├── olx/                        # Date OLX (brut, cache, cu marci extrase)
│   │   ├── cars.csv
│   │   ├── cars.jsonl
│   │   ├── cars_with_brands.csv          # <- folosit in pipeline
│   │   └── counts_cache.json
│   ├── bestauto/                   # Date BestAuto (brut, jsonl, checkpoint)
│   │   ├── bestauto.csv                  # <- folosit in pipeline
│   │   ├── bestauto.jsonl
│   │   └── bestauto_checkpoint.json
│   ├── mobilede/                   # Date Mobile.de (carduri, imbogatit, tradus)
│   │   ├── mobile_de.csv
│   │   ├── mobile_de.jsonl
│   │   ├── mobile_de_checkpoint.json
│   │   ├── mobile_de_full.csv
│   │   ├── mobile_de_full.jsonl
│   │   ├── mobile_de_full_checkpoint.json
│   │   └── mobile_de_ro.csv              # <- folosit in pipeline
│   └── centralized/                # Datasetul final unificat si graficele generate
│       ├── cars_centralized.csv
│       ├── distributii_dataset_centralizat.png
│       ├── pret_pe_sursa.png
│       └── corelatii_pret.png
├── docs/                           # Prezentari si documentatie de proiect
│   ├── Presentation - Predicția prețurilor autoturismelor.pdf
│   └── README.md
└── requirements.txt
```

---

## 🚗 Surse de Date si Volume Colectate

| Sursa | Tehnologie Scraping | Fisier folosit in pipeline | Inregistrari brute | In datasetul final | Caracteristici Principale Extrase |
|---|---|---|---:|---:|---|
| **OLX.ro** | curl_cffi + BeautifulSoup | `olx/cars_with_brands.csv` | 26.646 | 26.405 | Marca (dedusa din titlu/model), Model, Pret, An, Rulaj, Caroserie, Combustibil, Transmisie, Putere |
| **BestAuto.ro** | Requests + BeautifulSoup | `bestauto/bestauto.csv` | 24.144 | 23.420 | Marca, Model, Pret, An, Km, Putere, Capacitate, Combustibil, Transmisie, Caroserie |
| **Mobile.de** | Camoufox (Stealth Firefox) | `mobilede/mobile_de_ro.csv` | 19.992 | 19.384 | Marca, Model, Pret, An, Km, Putere, Combustibil + specificatii tehnice (vezi nota), traduse in romana |
| **AutoVit.ro** | Requests + BeautifulSoup | `autovit/autovit_prices_cleand.csv` | 18.454 | 16.750 | Marca, Model, Pret, An, Km, Combustibil, Capacitate, Putere, Caroserie |
| **TOTAL** | Pipeline `Faza_1_1.ipynb` | `centralized/cars_centralized.csv` | **89.236** | **85.959** | 17 coloane, fara duplicate si fara valori aberante |

Toate preturile sunt in EUR.

**Nota Mobile.de:** s-au colectat 20.000 de carduri (`mobile_de.csv`), din care 19.992 unice au ajuns in `mobile_de_ro.csv`. Doar **5.470 (27,4%)** au fisa tehnica completa, extrasa din pagina de detaliu a anuntului. Pentru celelalte 14.522, `enrich_mobile_de.py` **estimeaza** caroseria, capacitatea cilindrica, transmisia si numarul de usi din cuvintele cheie din titlu si din putere (de ex. caroserie implicita `Limousine`, transmisie automata daca puterea ≥ 200 CP). In datasetul final, 5.312 din cele 19.384 inregistrari Mobile.de au specificatii reale.

---

## 🔄 Pipeline-ul de Centralizare (`extraction/Faza_1_1.ipynb`)

| Pas | Operatie | Randuri |
|---|---|---:|
| 1 | Incarcarea celor 4 seturi de date si concatenarea pe cele 16 coloane comune + `source` | 89.236 |
| 2 | Eliminarea duplicatelor dupa `url` (50 randuri) | 89.186 |
| 3 | Deduplicare pe specificatii tehnice (`brand`, `model`, `year`, `engine_capacity`, `fuel_type`, `power`, `transmission`, `mileage`, `body_type`, `doors`), pastrand inregistrarea cea mai completa | 88.228 |
| 4 | Curatarea si normalizarea valorilor (vezi mai jos) | 88.228 |
| 5 | Filtrarea valorilor aberante | **85.959** |

**Curatari aplicate la pasul 4:**
- **An:** corectarea valorilor cu o cifra in plus (`20210` -> `2021`); la AutoVit se foloseste `Anul productiei`, completat cu anul din listare; la Mobile.de anul este extras din formatul `MM/YYYY`.
- **Pret:** eliminarea simbolului `€`, a spatiilor si conversia virgulei zecimale (OLX).
- **Kilometraj:** eliminarea sufixului `km` si conversia la intreg.
- **Capacitate cilindrica:** corectarea valorilor AutoVit formatate eronat (`19973` -> `1997`, `196830` -> `1968`) si conversia valorilor introduse in litri (`1.6` / `16` -> `1600` cm³).
- **Numar usi:** normalizare (`4/5` -> 5, `2/3` -> 3, `50.0` -> 5).
- **Categorii:** unificarea caroseriei (10 categorii), culorii, combustibilului (Diesel, Benzină, Hibrid, Benzină + GPL, Plug-in hybrid, Electric), transmisiei, starii si statusului de inmatriculare.

**Intervale valide la pasul 5** (valorile lipsa sunt pastrate):

| Coloana | Interval acceptat |
|---|---|
| `year` | 1950 – 2026 |
| `price` | 100 – 2.000.000 € |
| `mileage` | ≤ 1.500.000 km |
| `engine_capacity` | 400 – 10.000 cm³ |
| `power` | 20 – 2.000 CP |
| `doors` | 2 – 6 |

**Schema finala (17 coloane):** `body_type`, `brand`, `color`, `condition`, `doors`, `engine_capacity`, `fuel_type`, `mileage`, `model`, `power`, `price`, `registered`, `title`, `transmission`, `url`, `year`, `source`.

---

## 📊 Indicatori ai Datasetului Final

| Indicator | Valoare |
|---|---|
| Inregistrari | 85.959 |
| Marci distincte / modele distincte | 110 / 1.522 |
| Pret median | 9.800 € |
| An median de fabricatie | 2016 |
| Kilometraj median | 160.000 km |
| Putere mediana | 150 CP |
| Combustibil | Diesel 52,6%, Benzină 40,4%, Hibrid 3,6%, Benzină + GPL 1,7%, Plug-in hybrid 0,9%, Electric 0,9% |
| Transmisie (din valorile cunoscute) | Automată 62,2%, Manuală 37,8% |

**Pretul pe sursa:**

| Sursa | Pret median | P25 – P75 | An median | Km median |
|---|---:|---:|---:|---:|
| OLX | 5.990 € | 3.190 – 11.050 € | 2013 | 214.480 |
| BestAuto | 6.450 € | 3.700 – 10.000 € | 2013 | 209.000 |
| AutoVit | 15.972 € | 9.190 – 26.990 € | 2019 | 149.000 |
| Mobile.de | 30.900 € | 14.790 – 46.900 € | 2017 | 93.502 |

BestAuto si Mobile.de au fost colectate pe paliere de pret aproape egale, deci diferentele de pret intre surse reflecta partial designul de esantionare.

**Corelatia Spearman cu pretul:** an +0,76 · putere +0,71 · capacitate cilindrica +0,45 · numar usi +0,08 · kilometraj −0,57.

**Grafice generate** in `data/centralized/`:
- `distributii_dataset_centralizat.png` – anunturi per sursa, distributia anilor, top 10 marci, ponderea combustibililor.
- `pret_pe_sursa.png` – pretul median si intervalul intercuartilic pe fiecare platforma.
- `corelatii_pret.png` – corelatia Spearman a variabilelor numerice cu pretul.

---

## ⚙️ Mod de Rulare a Pipeline-ului

### 1. Instalare dependinte
```bash
pip install -r requirements.txt
```

### 2. Rulare notebook centralizator
Deschideti si rulati `extraction/Faza_1_1.ipynb` (functioneaza din `extraction/` sau din radacina repository-ului). Notebook-ul citeste cele 4 fisiere marcate mai sus din `data/`, scrie `data/centralized/cars_centralized.csv` si regenereaza cele 3 grafice.
