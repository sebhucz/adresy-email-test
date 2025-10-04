# /wyszukiwarka_emaili.py

import requests
import re
import csv
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from duckduckgo_search import DDGS
from time import sleep

# --- Konfiguracja ---
INPUT_FILENAME = 'spolki.txt'
OUTPUT_FILENAME = 'wyniki.csv'
PRIORITY_KEYWORDS = ['zarzad', 'sekretariat', 'biuro', 'board', 'office', 'kontakt', 'info', 'investor']
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

def find_company_website(company_name: str, krs_number: str) -> str | None:
    """Wyszukuje w internecie oficjalną stronę firmy, używając nazwy i numeru KRS."""
    print(f"🕵️‍♂️ Wyszukiwanie strony dla: '{company_name}' (KRS: {krs_number})...")
    # Dodanie numeru KRS do zapytania znacznie zwiększa trafność
    query = f'"{company_name}" KRS {krs_number} oficjalna strona internetowa'
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if not results:
                print("❌ Nie znaleziono wyników w wyszukiwarce.")
                return None
            
            first_url = results[0]['href']
            print(f"✅ Znaleziono potencjalną stronę: {first_url}")
            return first_url
    except Exception as e:
        print(f"🚨 Wystąpił błąd podczas wyszukiwania: {e}")
        return None

def get_soup(url: str) -> BeautifulSoup | None:
    """Pobiera zawartość strony i parsuje ją do obiektu BeautifulSoup."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'lxml')
    except requests.RequestException as e:
        print(f"🚨 Nie udało się pobrać strony {url}. Błąd: {e}")
        return None

def find_contact_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Przeszukuje stronę w poszukiwaniu linku do podstrony 'Kontakt'."""
    contact_keywords = ['kontakt', 'contact']
    for keyword in contact_keywords:
        link = soup.find('a', href=re.compile(keyword, re.IGNORECASE), string=re.compile(keyword, re.IGNORECASE))
        if link and link.get('href'):
            contact_url = urljoin(base_url, link['href'])
            print(f"✅ Znaleziono link do strony kontaktowej: {contact_url}")
            return contact_url
    return None

def find_emails_on_page(soup: BeautifulSoup) -> list[str]:
    """Wyszukuje wszystkie unikalne adresy e-mail na stronie."""
    found_emails = set()
    page_text = soup.get_text(separator=' ')
    
    # Szukanie w linkach mailto:
    mailto_links = soup.find_all('a', href=re.compile(r'^mailto:'))
    for link in mailto_links:
        found_emails.add(link['href'].replace('mailto:', '').split('?')[0].strip())

    # Szukanie za pomocą RegEx w całym tekście
    all_emails_in_text = re.findall(EMAIL_REGEX, page_text)
    for email in all_emails_in_text:
        # Prosta walidacja, by odrzucić fałszywe dopasowania (np. w nazwach plików)
        if not email.endswith(('.png', '.jpg', '.gif', '.svg', '.webp')):
            found_emails.add(email)
            
    return list(found_emails)

def save_results_to_csv(results: list, filename: str):
    """Zapisuje zebrane wyniki do pliku CSV."""
    if not results:
        print("ℹ️ Nie znaleziono żadnych danych do zapisania.")
        return

    print(f"\n💾 Zapisywanie wyników do pliku {filename}...")
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['nazwa_spolki', 'krs', 'strona_www', 'znalezione_emaile']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print("✅ Wyniki zostały pomyślnie zapisane.")

def main():
    """Główna funkcja sterująca, która czyta plik wejściowy i przetwarza każdą firmę."""
    all_results = []
    
    try:
        with open(INPUT_FILENAME, 'r', encoding='utf-8') as f:
            companies = f.readlines()
    except FileNotFoundError:
        print(f"🚨 BŁĄD: Nie znaleziono pliku wejściowego '{INPUT_FILENAME}'. Utwórz go i dodaj dane.")
        return

    for index, line in enumerate(companies):
        line = line.strip()
        if not line or ';' not in line:
            continue # Pomiń puste lub niepoprawnie sformatowane linie

        company_name, krs_number = [part.strip() for part in line.split(';', 1)]
        
        print(f"\n{'='*20} Przetwarzanie: {company_name} ({index+1}/{len(companies)}) {'='*20}")
        
        website_url = find_company_website(company_name, krs_number)
        found_emails = set()

        if website_url:
            main_page_soup = get_soup(website_url)
            if main_page_soup:
                found_emails.update(find_emails_on_page(main_page_soup))

                contact_page_url = find_contact_page_url(main_page_soup, website_url)
                if contact_page_url and contact_page_url != website_url:
                    sleep(1) # Mała pauza, by nie obciążać serwera
                    contact_page_soup = get_soup(contact_page_url)
                    if contact_page_soup:
                        found_emails.update(find_emails_on_page(contact_page_soup))

        # Sortowanie z priorytetem
        sorted_emails = sorted(
            list(found_emails),
            key=lambda email: not any(keyword in email.lower() for keyword in PRIORITY_KEYWORDS)
        )

        print(f"📧 Podsumowanie dla {company_name}: Znaleziono {len(sorted_emails)} e-maili.")
        
        # Przygotowanie rekordu do zapisu
        result_row = {
            'nazwa_spolki': company_name,
            'krs': krs_number,
            'strona_www': website_url or "Nie znaleziono",
            'znalezione_emaile': ", ".join(sorted_emails) # E-maile oddzielone przecinkiem
        }
        all_results.append(result_row)
        
        # Dodajemy pauzę między zapytaniami do różnych firm
        sleep(2) 

    # Zapisz wszystkie zebrane wyniki do pliku CSV
    save_results_to_csv(all_results, OUTPUT_FILENAME)

if __name__ == "__main__":
    main()
