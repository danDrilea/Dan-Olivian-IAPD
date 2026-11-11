# Documentatie si Prezentari

Acest director contine materialele de prezentare ale proiectului:

- **`Presentation - Predicția prețurilor autoturismelor.pdf`**: prezentarea de Faza 1 (11 slide-uri):
  1. **Titlu**: Predicția prețurilor autoturismelor – IAPD Proiect Faza 1.
  2. **Ideea proiectului**: fragmentarea pietei auto second-hand si lipsa unei referinte obiective pentru preturi si caracteristici tehnice.
  3. **Achizitia datelor**: OLX (26.646 anunturi, BeautifulSoup), AutoVit (18.454 anunturi pe 9 segmente), BestAuto (24.144 anunturi in EUR).
  4. **Scraping robust**: tehnici de persistenta (checkpointing), gestionarea erorilor si deduplicare.
  5. **Preprocesare**: curatarea a ~89k randuri si unificarea taxonomiilor din cele 4 surse.
  6. **Limitari**: la Mobile.de doar 27% dintre anunturi au fisa tehnica completa.
  7. **Statistici descriptive**: 85.959 anunturi in datasetul final, pret mediu 17.267 EUR, distributie asimetrica a preturilor.
  8. **Corelatii**: corelatia Spearman a pretului cu anul, puterea, capacitatea cilindrica, numarul de usi si kilometrajul (`data/centralized/corelatii_pret.png`).
  9. **Variatia pretului**: pretul median si intervalul P25–P75 pe fiecare sursa (`data/centralized/pret_pe_sursa.png`).
  10. **Analize intentionate**: regresie liniara regularizata Ridge, apoi Random Forest Regressor; evaluare cu 5-fold cross-validation folosind MAE si RMSE.
  11. **Multumiri**.

Cifrele din prezentare provin din `extraction/Faza_1_1.ipynb` si din `data/centralized/cars_centralized.csv`. Detaliile complete ale pipeline-ului si indicatorii datasetului sunt in [README-ul principal](../README.md).
