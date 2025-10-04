# Company Contact Finder (Google API)

Czyta spółki z `nazwy.txt`, znajduje oficjalną domenę przez **Google Custom Search**,
przeszukuje podstrony i wyciąga e-maile (z rolą, pewnością i cytatem).

## Jak uruchomić lokalnie
1) Zainstaluj Pythona 3.10+  
2) `python -m venv .venv && . .venv/bin/activate` (Windows: `.venv\Scripts\activate`)  
3) `pip install -r requirements.txt`  
4) Ustaw zmienne środowiskowe:
   - `GOOGLE_API_KEY` – klucz do Google Custom Search JSON API  
   - `GOOGLE_CX` – ID wyszukiwarki (Programmable Search Engine)
5) `python main.py`  
Wyniki: `out/results.json`, `out/results.csv`, oraz źródła w `out/pages/`.

## Jak uruchomić na GitHubie (Actions)
1) Repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `GOOGLE_API_KEY` = Twój klucz
   - `GOOGLE_CX` = Twoje CX (ID wyszukiwarki)
2) Workflow znajduje się w `.github/workflows/run.yml`. Po pushu wykona się i zapisze artefakty z wynikami.

## Uwaga
- API Google ma limit darmowy ~100 zapytań/dzień.  
- Skrypt zbiera tylko jawnie opublikowane dane firmowe i zapisuje „ślady” (URL+snippet+snapshot).
# adresy-email-test
