"""
Script de traducere si normalizare in limba romana pentru dataset-ul mobile_de_full.csv.

Traduce si normalizeaza toate informatiile din limba germana:
1. body_type (tip caroserie): Limousine -> Berlina, Kleinwagen -> Hatchback, Kombi -> Combi etc.
2. fuel_type (combustibil): Benzin -> Benzina, Diesel, Electric, GPL, Hibrid etc.
3. air_conditioning (climatizare): Klimaanlage -> Aer conditionat manual, Klimaautomatik -> Climatizare automata etc.
4. condition (stare vehicul): Gebrauchtfahrzeug -> Utilizat, Unfallfrei -> Fara accident etc.
5. seller_name: 'Privatanbieter' -> 'Persoana fizica'
6. seller_country: 'DE' -> 'Germania'
7. features: Toate cele 129 de dotari auto individuale preluate din germana sunt traduse in romana
8. color: Traducere descriere culoare + extragere culoare de baza standardizata ('color_base')
9. title & model: Traducere termeni, abrevieri si expresii tehnice auto germane
10. accident_free / damaged: Standardizate
11. Optional: Redenumirea antetelor de coloane in limba romana
"""

import os
import re
import argparse
import pandas as pd

# ==============================================================================
# 1. CAROSERIE (body_type)
# ==============================================================================
BODY_TYPE_MAP = {
    'Limousine': 'Berlina',
    'Kombi': 'Combi',
    'SUV': 'SUV',
    'Kleinwagen': 'Hatchback',
    'Coupé': 'Coupé',
    'Van/Minibus': 'Monovolum',
    'Van / Minibus': 'Monovolum',
    'Cabrio': 'Cabrio',
    'Cabrio/Roadster': 'Cabrio',
    'SUV/Geländewagen/Pickup': 'SUV / Teren / Pickup',
    'Sportwagen/Coupé': 'Masina sport / Coupé',
    'Andere': 'Altele',
    'Kleinwagen, Vorführfahrzeug': 'Hatchback, Vehicul de prezentare',
    'Kleinwagen, Tageszulassung': 'Hatchback, Inmatriculare de o zi',
}

# ==============================================================================
# 2. COMBUSTIBIL (fuel_type)
# ==============================================================================
FUEL_TYPE_MAP = {
    'Petrol': 'Benzina',
    'Benzin': 'Benzina',
    'Benzin, E10-geeignet': 'Benzina (compatibil E10)',
    'Diesel': 'Diesel',
    'Electric': 'Electric',
    'Diesel, Biodiesel geeignet': 'Diesel (compatibil biodiesel)',
    'Benzin, Biodiesel geeignet, E10-geeignet': 'Benzina (compatibil biodiesel, E10)',
    'Hybrid (Benzin/Elektro), Plug-in-Hybrid': 'Hibrid plug-in (benzina/electric)',
    'LPG': 'GPL',
}

# ==============================================================================
# 3. CLIMATIZARE (air_conditioning)
# ==============================================================================
AIR_CONDITIONING_MAP = {
    'Klimaanlage': 'Aer conditionat manual',
    '2-Zonen-Klimaautomatik': 'Climatizare automata (2 zone)',
    'Klimaautomatik': 'Climatizare automata',
    '3-Zonen-Klimaautomatik': 'Climatizare automata (3 zone)',
    'Keine Klimaanlage oder -automatik': 'Fara climatizare',
    '4-Zonen-Klimaautomatik': 'Climatizare automata (4 zone)',
}

# ==============================================================================
# 4. STARE (condition)
# ==============================================================================
CONDITION_MAP = {
    'Gebrauchtfahrzeug': 'Utilizat',
    'Gebrauchtfahrzeug, Unfallfrei': 'Utilizat, Fara accident',
    'Gebrauchtfahrzeug, Reparierter Unfallschaden': 'Utilizat, Dauna reparata',
    'Gebrauchtfahrzeug, Unfallfrei, Nicht fahrtauglich': 'Utilizat, Fara accident, Neutilizabil',
    'Gebrauchtfahrzeug, Nicht fahrtauglich': 'Utilizat, Neutilizabil',
    'Gebrauchtfahrzeug, Reparierter Unfallschaden, Nicht fahrtauglich': 'Utilizat, Dauna reparata, Neutilizabil',
    'Gebrauchtfahrzeug, Beschädigt, Unfallfrei': 'Utilizat, Avariat, Fara accident',
}

# ==============================================================================
# 5. TARA SI VANZATOR
# ==============================================================================
COUNTRY_MAP = {
    'DE': 'Germania',
}

SELLER_MAP = {
    'Privatanbieter': 'Persoana fizica',
}

# ==============================================================================
# 6. DICTIONAR COMPLET PENTRU TOATE CELE 129 DE DOTARI (features)
# ==============================================================================
FEATURES_MAP = {
    'ABS': 'ABS',
    'Abgedunkelte Scheiben': 'Geamuri fumurii',
    'Abstandstempomat': 'Pilot automat adaptiv (ACC)',
    'Abstandswarner': 'Avertizare coliziune frontala / distanta',
    'Adaptives Fahrwerk': 'Suspensie adaptiva',
    'Adaptives Kurvenlicht': 'Faruri adaptive in viraje',
    'Alarmanlage': 'Alarma',
    'Allradantrieb': 'Tractiune integrala (4x4)',
    'Allwetterreifen': 'Anvelope all-season',
    'Ambiente-Beleuchtung': 'Iluminare ambientala',
    'Android Auto': 'Android Auto',
    'Anhängerkupplung': 'Carlig de remorcare',
    'Anhängerkupplung abnehmbar': 'Carlig de remorcare detasabil',
    'Anhängerkupplung fest': 'Carlig de remorcare fix',
    'Anhängerkupplung schwenkbar': 'Carlig de remorcare rabatabil',
    'Anhängerkupplung-Vorbereitung': 'Pregatire carlig de remorcare',
    'Anhängerrangierassistent': 'Asistenta manevrare remorca',
    'Apple CarPlay': 'Apple CarPlay',
    'Armlehne': 'Cotiera',
    'Ausparkassistent': 'Asistenta iesire din parcare',
    'Batteriezertifikat': 'Certificat baterie',
    'Beheizbare Frontscheibe': 'Parbriz incalzit',
    'Beheizbares Lenkrad': 'Volan incalzit',
    'Behindertengerecht': 'Adaptat persoane cu dizabilitati',
    'Berganfahrassistent': 'Asistenta pornire in rampa',
    'Bi-Xenon Scheinwerfer': 'Faruri Bi-Xenon',
    'Blendfreies Fernlicht': 'Faza lunga automata fara orbire',
    'Bluetooth': 'Bluetooth',
    'Bordcomputer': 'Computer de bord',
    'CD-Spieler': 'CD player',
    'Dachreling': 'Bare plafon',
    'ESP': 'ESP',
    'Einparkhilfe': 'Senzori parcare',
    'Elektr. Fensterheber': 'Geamuri electrice',
    'Elektr. Heckklappe': 'Portbagaj electric',
    'Elektr. Seitenspiegel': 'Oglinzi electrice',
    'Elektr. Seitenspiegel anklappbar': 'Oglinzi rabatabile electric',
    'Elektr. Sitzeinstellung': 'Scaune reglabile electric',
    'Elektr. Sitzeinstellung mit Memory-Funktion': 'Scaune electrice cu memorie',
    'Elektr. Wegfahrsperre': 'Imobilizator electronic',
    'Faltdach': 'Plafon retractabil textil',
    'Fernlichtassistent': 'Asistent faza lunga',
    'Freisprecheinrichtung': 'Kit maini libere (Handsfree)',
    'Frontantrieb': 'Tractiune fata',
    'Garantie': 'Garantie',
    'Gepäckraumabtrennung': 'Separator portbagaj',
    'Geschwindigkeitsbegrenzer': 'Limitator de viteza',
    'Head-Up Display': 'Head-Up Display',
    'Heckantrieb': 'Tractiune spate',
    'Induktionsladen für Smartphones': 'Incarcare wireless smartphone',
    'Innenspiegel autom. abblendend': 'Oglinda retrovizoare antiorbire',
    'Inspektion neu': 'Revizie recenta',
    'Isofix': 'Isofix',
    'Isofix Beifahrersitz': 'Isofix scaun pasager',
    'Klimaanlage': 'Aer conditionat manual',
    'Klimaautomatik': 'Climatizare automata',
    'Kurvenlicht': 'Lumini de viraj',
    'LED-Scheinwerfer': 'Faruri LED',
    'LED-Tagfahrlicht': 'Lumini de zi LED',
    'Laserlicht': 'Faruri laser',
    'Lederausstattung': 'Tapiterie piele',
    'Lederlenkrad': 'Volan din piele',
    'Leichtmetallfelgen': 'Jante din aliaj',
    'Lichtsensor': 'Senzor de lumina',
    'Lordosenstütze': 'Suport lombar',
    'Luftfederung': 'Suspensie pneumatica',
    'Massagesitze': 'Scaune cu masaj',
    'Multi-CD-Wechsler': 'Magazie CD',
    'Multifunktionslenkrad': 'Volan multifunctional',
    'Musikstreaming integriert': 'Streaming audio integrat',
    'Müdigkeitswarner': 'Avertizare oboseala sofer',
    'Nachtsicht-Assistent': 'Night Vision',
    'Navigationssystem': 'Sistem de navigatie',
    'Navigationsvorbereitung': 'Pregatire navigatie',
    'Nebelscheinwerfer': 'Proiectoare ceata',
    'Nichtraucher-Fahrzeug': 'Vehicul de nefumatori',
    'Notbremsassistent': 'Asistenta franare de urgenta',
    'Notrad': 'Roata de rezerva ingusta',
    'Notrufsystem': 'Sistem apel urgenta (eCall)',
    'Pannenkit': 'Kit pana',
    'Panorama-Dach': 'Plafon panoramic',
    'Panoramadach': 'Plafon panoramic',
    'Partikelfilter': 'Filtru de particule',
    'Radio DAB': 'Radio DAB',
    'Raucherpaket': 'Pachet fumatori',
    'Rechtslenker': 'Volan pe dreapta',
    'Regensensor': 'Senzor de ploaie',
    'Reifendruckkontrolle': 'Monitorizare presiune pneuri',
    'Reserverad': 'Roata de rezerva',
    'Schaltwippen': 'Padele volan',
    'Scheckheftgepflegt': 'Carte de service',
    'Scheinwerferreinigung': 'Spalator faruri',
    'Schiebedach': 'Trapa',
    'Schlüssellose Zentralverriegelung (Keyless)': 'Inchidere centralizata fara cheie (Keyless)',
    'Servolenkung': 'Servodirectie',
    'Sitzbelüftung': 'Ventilatie in scaune',
    'Sitzheizung': 'Incalzire in scaune',
    'Sitzheizung hinten': 'Incalzire in scaune spate',
    'Skisack': 'Sac pentru schiuri',
    'Sommerreifen': 'Anvelope de vara',
    'Soundsystem': 'Sistem audio',
    'Sportfahrwerk': 'Suspensie sport',
    'Sportpaket': 'Pachet sport',
    'Sportsitze': 'Scaune sport',
    'Sprachsteuerung': 'Comenzi vocale',
    'Spurhalteassistent': 'Asistenta mentinere banda',
    'Stahlfelgen': 'Jante de otel',
    'Standheizung': 'Incalzire auxiliara (Webasto)',
    'Start/Stopp-Automatik': 'Sistem Start/Stop',
    'TV': 'TV',
    'Tagfahrlicht': 'Lumini de zi',
    'Taxi': 'Taxi',
    'Tempomat': 'Pilot automat (Cruise Control)',
    'Totwinkel-Assistent': 'Asistenta unghi mort',
    'Touchscreen': 'Ecran tactil',
    'Traktionskontrolle': 'Controlul tractiunii',
    'Tuner/Radio': 'Radio',
    'USB': 'USB',
    'Umklappbarer Beifahrersitz': 'Scaun pasager rabatabil',
    'Verkehrszeichenerkennung': 'Recunoastere semne circulatie',
    'Virtuelle Seitenspiegel': 'Oglinzi laterale digitale',
    'Volldigitales Kombiinstrument': 'Bord digital (Virtual Cockpit)',
    'WLAN / Wifi Hotspot': 'Hotspot Wi-Fi',
    'Winterpaket': 'Pachet de iarna',
    'Winterreifen': 'Anvelope de iarna',
    'Wärmepumpe': 'Pompa de caldura',
    'Xenonscheinwerfer': 'Faruri Xenon',
    'Zentralverriegelung': 'Inchidere centralizata',
    'hinten': 'Spate'
}

# ==============================================================================
# 7. TRADUCERE SI EXTRAGERE CULORI (color & color_base)
# ==============================================================================
COLOR_WORD_MAP = {
    'schwarz': 'negru', 'black': 'negru', 'noir': 'negru', 'zwart': 'negru',
    'weiß': 'alb', 'weiss': 'alb', 'white': 'alb', 'blanc': 'alb',
    'grau': 'gri', 'grey': 'gri', 'gray': 'gri', 'gris': 'gri', 'anthrazit': 'antracit',
    'silber': 'argintiu', 'silver': 'argintiu', 'aluminium': 'aluminiu',
    'blau': 'albastru', 'blue': 'albastru', 'blu': 'albastru',
    'rot': 'rosu', 'red': 'rosu', 'rouge': 'rosu', 'rosso': 'rosu', 'rubi': 'rubiniu',
    'braun': 'maro', 'brown': 'maro', 'bronze': 'bronz',
    'grün': 'verde', 'gruen': 'verde', 'green': 'verde',
    'gelb': 'galben', 'yellow': 'galben',
    'orange': 'portocaliu',
    'beige': 'bej',
    'gold': 'auriu',
    'violett': 'violet', 'lila': 'lila', 'purple': 'violet',
    'metallic': 'metalizat', 'metalliclack': 'metalizat',
    'perleffekt': 'perlat', 'pearl': 'perlat',
    'foliert': 'colantat',
    'matt': 'mat', 'matte': 'mat',
    'dunkel': 'inchis', 'hell': 'deschis',
    'unilack': 'nemetalizat'
}

def translate_color_text(val):
    """Traduce descrierea originala a culorii in limba romana."""
    if not isinstance(val, str) or not val.strip():
        return val
    text = val
    for de, ro in sorted(COLOR_WORD_MAP.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(rf'\b{re.escape(de)}\b', re.IGNORECASE)
        text = pattern.sub(ro, text)
        if de in ['silber', 'silver', 'weiss', 'weiß', 'schwarz', 'grau', 'blau', 'rot', 'braun', 'grün']:
            pattern_sub = re.compile(re.escape(de), re.IGNORECASE)
            text = pattern_sub.sub(f' {ro} ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.capitalize()

def extract_base_color(val):
    """Extrage categoria standardizata de culoare (Negru, Alb, Gri, Argintiu, etc.)."""
    if not isinstance(val, str) or not val.strip():
        return None
    v = val.lower()
    if any(k in v for k in ['schwarz', 'black', 'noir', 'zwart', 'negru']): return 'Negru'
    if any(k in v for k in ['weiß', 'weiss', 'white', 'blanc', 'alb']): return 'Alb'
    if any(k in v for k in ['silber', 'silver', 'argintiu', 'argint', 'reflexsilber', 'polarsilber']): return 'Argintiu'
    if any(k in v for k in ['grau', 'grey', 'gray', 'anthrazit', 'gris', 'magnetic', 'gri']): return 'Gri'
    if any(k in v for k in ['blau', 'blue', 'blu', 'albastru']): return 'Albastru'
    if any(k in v for k in ['rot', 'red', 'rouge', 'rosso', 'rosu', 'rubi']): return 'Rosu'
    if any(k in v for k in ['braun', 'brown', 'bronze', 'maro']): return 'Maro'
    if any(k in v for k in ['grün', 'gruen', 'green', 'verde']): return 'Verde'
    if any(k in v for k in ['gelb', 'yellow', 'galben']): return 'Galben'
    if any(k in v for k in ['orange', 'portocaliu']): return 'Portocaliu'
    if any(k in v for k in ['beige', 'bej']): return 'Bej'
    if any(k in v for k in ['gold', 'auriu']): return 'Auriu'
    if any(k in v for k in ['violett', 'lila', 'purple', 'violet']): return 'Violet'
    return 'Alta culoare'

# ==============================================================================
# 8. TERMENI FRECVENTI IN TITLURI SI MODELE (title / model)
# ==============================================================================
TITLE_KEYWORDS = [
    (r'(?i)Lieferung\s*m[öo]glich', 'posibilitate livrare'),
    (r'(?i)\b2\.?\s*Hand\b', 'al 2-lea proprietar'),
    (r'(?i)\b1\.?\s*Hand\b', 'primul proprietar'),
    (r'(?i)\bT[ÜU]V\s*Neu\b', 'ITP Nou'),
    (r'(?i)\bT[ÜU]V\b', 'ITP'),
    (r'(?i)\bTüv\b', 'ITP'),
    (r'(?i)\bHU/AU\s*neu\b', 'ITP Nou'),
    (r'(?i)\bHU/AU\b', 'ITP'),
    (r'(?i)\bKlimaanlage\b', 'Aer conditionat'),
    (r'(?i)\bKlimaautomatik\b', 'Climatronic'),
    (r'(?i)\bKlima\b', 'AC'),
    (r'(?i)\belektrische\s+Fensterheber\b', 'geamuri electrice'),
    (r'(?i)\bEFH\b', 'geamuri electrice'),
    (r'(?i)\bNichtraucher-Fahrzeug\b', 'vehicul nefumator'),
    (r'(?i)\bNichtraucher\b', 'nefumator'),
    (r'(?i)\bScheckheftgepflegt\b', 'carte service'),
    (r'(?i)\bScheckheft\s*gepflegt\b', 'carte service'),
    (r'(?i)\bScheckheft\b', 'carte service'),
    (r'(?i)\bAutomatik\b', 'Automat'),
    (r'(?i)\bSchaltgetriebe\b', 'Manual'),
    (r'(?i)\bSchalter\b', 'Manual'),
    (r'(?i)\bPanoramadach\b', 'Plafon panoramic'),
    (r'(?i)\bPanorama-Dach\b', 'Plafon panoramic'),
    (r'(?i)\bPano\b', 'Plafon panoramic'),
    (r'(?i)\bSchiebedach\b', 'Trapa'),
    (r'(?i)\bAnh[äa]ngerkupplung\b', 'Carlig remorcare'),
    (r'(?i)\bAHK\b', 'Carlig remorcare'),
    (r'(?i)\bAlufelgen\b', 'Jante aliaj'),
    (r'(?i)\bAlu\b', 'Aliaj'),
    (r'(?i)\bStandheizung\b', 'Webasto'),
    (r'(?i)\bSitzheizung\b', 'Incalzire scaune'),
    (r'(?i)\bSHZ\b', 'Incalzire scaune'),
    (r'(?i)\bTempomat\b', 'Pilot automat'),
    (r'(?i)\bWinterreifen\b', 'Anvelope iarna'),
    (r'(?i)\bSommerreifen\b', 'Anvelope vara'),
    (r'(?i)\bAllwetterreifen\b', 'Anvelope all-season'),
    (r'(?i)\bAllwetterr\.\b', 'Anvelope all-season'),
    (r'(?i)\bInspektion\s*neu\b', 'Revizie noua'),
    (r'(?i)\bZahnriemen\s*neu\b', 'Distributie noua'),
    (r'(?i)\bBremsen\s*neu\b', 'Frane noi'),
    (r'(?i)\bSehr\s*Gepflegt\b', 'Foarte intretinut'),
    (r'(?i)\bSehr\s*gepflegt\b', 'Foarte intretinut'),
    (r'(?i)\bTop\s*Zustand\b', 'Stare impecabila'),
    (r'(?i)\bUnfallfrei\b', 'Fara accident'),
    (r'(?i)\bBesch[äa]digt\b', 'Avariat'),
    (r'(?i)\bKein\s*T[ÜU]V\b', 'Fara ITP'),
    (r'(?i)\bWenig\s*KM\b', 'Km putini'),
    (r'(?i)\bR[üu]ckfahrkamera\b', 'Camera marsarier'),
    (r'(?i)\bKamera\b', 'Camera'),
    (r'(?i)\bSportpaket\b', 'Pachet sport'),
    (r'(?i)\bSportsitze\b', 'Scaune sport'),
    (r'(?i)\bLeder\b', 'Piele'),
    (r'(?i)\bNavi\b', 'Navigatie'),
    (r'(?i)\b5-T[üu]rer\b', '5 usi'),
    (r'(?i)\b3-T[üu]rig\b', '3 usi'),
    (r'(?i)\b5-T[üu]rig\b', '5 usi'),
    (r'(?i)\bNEU\b', 'NOU'),
]

def translate_title_terms(text):
    """Traduce cuvintele cheie germane des intalnite in titluri/modele."""
    if not isinstance(text, str) or not text.strip():
        return text
    res = text
    for pattern, replacement in TITLE_KEYWORDS:
        res = re.sub(pattern, replacement, res)
    return res

# ==============================================================================
# 9. REDENUMIRE OPTIONALA A NUMELOR COLOANELOR IN ROMANA
# ==============================================================================
COLUMN_NAME_RO = {
    'title': 'titlu',
    'price': 'pret',
    'currency': 'moneda',
    'body_type': 'caroserie',
    'mileage_km': 'kilometraj_km',
    'engine_displacement_cm3': 'capacitate_cilindrica_cm3',
    'power_kw': 'putere_kw',
    'power_hp': 'putere_cp',
    'transmission': 'cutie_viteze',
    'fuel_type': 'combustibil',
    'first_registration': 'prima_inmatriculare',
    'euro_standard': 'norma_euro',
    'doors': 'numar_usi',
    'seats': 'numar_locuri',
    'color': 'culoare',
    'color_base': 'culoare_baza',
    'condition': 'stare',
    'accident_free': 'fara_accident',
    'damaged': 'avariata',
    'air_conditioning': 'climatizare',
    'features': 'dotari',
    'listing_id': 'id_anunt',
    'listing_url': 'url_anunt',
    'brand': 'marca',
    'model': 'model',
    'seller_name': 'nume_vanzator',
    'seller_city': 'oras_vanzator',
    'seller_postal_code': 'cod_postal_vanzator',
    'seller_country': 'tara_vanzator',
    'price_bracket': 'interval_pret',
    'source': 'sursa',
    'scraped_at': 'data_colectare'
}

# ==============================================================================
# 10. SEPARARE BRAND SI MODEL
# ==============================================================================
MULTIWORD_BRANDS = [
    'Alfa Romeo',
    'Aston Martin',
    'DS Automobiles',
    'Land Rover',
    'Rolls-Royce',
    'Mercedes-Benz',
]

def split_brand_field(val: str) -> tuple[str, str]:
    """Imparte textul compus din 'brand' in marca si model."""
    if not isinstance(val, str) or not val.strip():
        return '', ''
    text = val.strip()
    for mb in MULTIWORD_BRANDS:
        if text.startswith(mb + ' '):
            return mb, text[len(mb):].strip()
        elif text == mb:
            return mb, ''
    parts = text.split(' ', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ''

# ==============================================================================
# FUNCTIA PRINCIPALA DE TRADUCERE
# ==============================================================================
def translate_dataframe(df: pd.DataFrame, translate_titles: bool = True, rename_cols: bool = False) -> pd.DataFrame:
    """Aplica toate traducerile pe DataFrame."""
    df_out = df.copy()

    # 1. Caroserie
    print("Traducere 'body_type'...")
    df_out['body_type'] = df_out['body_type'].map(BODY_TYPE_MAP).fillna(df_out['body_type'])

    # 2. Combustibil
    print("Traducere 'fuel_type'...")
    df_out['fuel_type'] = df_out['fuel_type'].map(FUEL_TYPE_MAP).fillna(df_out['fuel_type'])

    # 3. Climatizare
    print("Traducere 'air_conditioning'...")
    df_out['air_conditioning'] = df_out['air_conditioning'].map(AIR_CONDITIONING_MAP).fillna(df_out['air_conditioning'])

    # 4. Stare
    print("Traducere 'condition'...")
    df_out['condition'] = df_out['condition'].map(CONDITION_MAP).fillna(df_out['condition'])

    # 5. Vanzator & Tara
    print("Traducere 'seller_name' si 'seller_country'...")
    df_out['seller_name'] = df_out['seller_name'].replace(SELLER_MAP)
    df_out['seller_country'] = df_out['seller_country'].replace(COUNTRY_MAP)

    # 6. Dotari (features)
    print("Traducere 'features' (129 de dotari)...")
    def translate_features_list(feat_str):
        if not isinstance(feat_str, str) or not feat_str.strip():
            return feat_str
        items = [f.strip() for f in feat_str.split(',') if f.strip()]
        translated = [FEATURES_MAP.get(item, item) for item in items]
        return ', '.join(translated)

    df_out['features'] = df_out['features'].apply(translate_features_list)

    # 7. Culoare
    print("Traducere si extragere culoare ('color' & 'color_base')...")
    df_out['color_base'] = df_out['color'].apply(extract_base_color)
    df_out['color'] = df_out['color'].apply(translate_color_text)

    # 8. Titlu si Model (optional / termeni tehnici)
    if translate_titles:
        print("Traducere termeni germani din 'title'...")
        df_out['title'] = df_out['title'].apply(translate_title_terms)

    # 9. Separare 'brand' in Marca si Model (inlocuind vechiul 'model')
    print("Separare 'brand' in Marca si Model...")
    splits = [split_brand_field(v) for v in df_out['brand']]
    new_brands, new_models = zip(*splits)
    df_out['brand'] = new_brands
    df_out['model'] = new_models

    # 10. Redenumire coloane (optional)
    if rename_cols:
        print("Redenumire coloane in limba romana...")
        df_out = df_out.rename(columns=COLUMN_NAME_RO)

    return df_out

def main():
    from pathlib import Path
    default_input = Path(__file__).resolve().parents[2] / "data" / "mobilede" / "mobile_de_full.csv"
    default_output = Path(__file__).resolve().parents[2] / "data" / "mobilede" / "mobile_de_ro.csv"

    parser = argparse.ArgumentParser(description="Traducere dataset mobile_de_full.csv in limba romana.")
    parser.add_argument("--input", default=str(default_input), help="Calea catre fisierul CSV de intrare")
    parser.add_argument("--output", default=str(default_output), help="Calea catre fisierul CSV tradus")
    parser.add_argument("--inplace", action="store_true", help="Suprascrie fisierul de intrare (creeaza automat .bak)")
    parser.add_argument("--rename-columns", action="store_true", help="Redenumeste si anteturile coloanelor in romana")
    parser.add_argument("--no-titles", action="store_true", help="Nu traduce termenii din titlu/model")

    args = parser.parse_args()

    input_path = os.path.normpath(args.input)
    output_path = os.path.normpath(args.output)

    if not os.path.exists(input_path):
        print(f"Eroare: Fisierul '{input_path}' nu a fost gasit!")
        return

    print(f"Incarcare fisier: {input_path}")
    df = pd.read_csv(input_path, low_memory=False)
    print(f"Dataset incarcat cu succes! Linii: {len(df)}, Coloane: {len(df.columns)}")

    df_translated = translate_dataframe(
        df,
        translate_titles=not args.no_titles,
        rename_cols=args.rename_columns
    )

    if args.inplace:
        bak_path = input_path + ".bak"
        if not os.path.exists(bak_path):
            print(f"Creare copie de siguranta: {bak_path}")
            df.to_csv(bak_path, index=False)
        output_path = input_path

    print(f"Salvare fisier tradus: {output_path}")
    try:
        df_translated.to_csv(output_path, index=False)
    except PermissionError:
        fallback_path = output_path.replace(".csv", "_nou.csv")
        print(f"\n[ATENTIE] Fisierul '{output_path}' este deschis intr-o alta aplicatie (ex: Excel).")
        print(f"Se salveaza in fisierul alternativ: {fallback_path}")
        df_translated.to_csv(fallback_path, index=False)
        output_path = fallback_path

    print("Gata! Traducerea s-a incheiat cu succes in:", output_path)

if __name__ == "__main__":
    main()
