import os, re, json, csv, asyncio, hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin
import httpx
import tldextract
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
import trafilatura

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX = os.getenv("GOOGLE_CX", "")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "20"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "6"))

EMAIL_REGEX = re.compile(r"(?i)[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}")
MAILTO_REGEX = re.compile(r"(?i)mailto:([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})")
CFEMAIL_REGEX = re.compile(r"data-cfemail=\"([0-9a-fA-F]+)\"")
SPACES_RE = re.compile(r"\s+")

COMMON_PATHS = [
    "", "kontakt", "contact", "contacts", "o-nas", "about", "company",
    "zarzad", "management", "governance", "press", "media",
    "investor-relations", "ir", "impressum"
]

def ensure_dirs():
    Path("out/pages").mkdir(parents=True, exist_ok=True)

def read_companies(path="nazwy.txt"):
    if not Path(path).exists():
        raise FileNotFoundError("Brak pliku nazwy.txt w katalogu głównym repo.")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # obsługa separatorów | i ;
            if "|" in line:
                name, krs = [x.strip() for x in line.split("|", 1)]
            elif ";" in line:
                name, krs = [x.strip() for x in line.split(";", 1)]
            else:
                name, krs = line, ""
            rows.append({"company": name, "krs": krs})
    return rows

def norm_company(name: str) -> str:
    stripped = re.sub(r"\b(s\.a\.|sa|sp\. z o\.o\.|spolka|spółka|s\.k\.a\.)\b", "", name, flags=re.I)
    return SPACES_RE.sub(" ", stripped).strip()

def extract_registered_domain(host_or_email_domain: str) -> str:
    ext = tldextract.extract(host_or_email_domain)
    return ".".join(part for part in [ext.domain, ext.suffix] if part)

def cfemail_decode(hex_string: str) -> str:
    data = bytes.fromhex(hex_string)
    key = data[0]
    decoded = bytes([b ^ key for b in data[1:]])
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return ""

def deobfuscate_text(txt: str) -> str:
    txt = txt.replace("[at]", "@").replace("(at)", "@").replace(" at ", "@")
    txt = txt.replace("[dot]", ".").replace("(dot)", ".").replace(" dot ", ".")
    return txt

async def fetch(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent":"Mozilla/5.0 (contact-finder/1.0)"})
        if 200 <= r.status_code < 400:
            return r.text
    except Exception:
        return ""
    return ""

async def google_candidates(company: str, krs: str) -> list[str]:
    urls = []
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        # tryb offline – zgaduj domenę z nazwy
        base = norm_company(company).replace(" ", "")
        return [f"https://{base}.pl", f"https://{base}.com"]

    queries = [
        f'{company} oficjalna strona kontakt',
        f'"{company}" KRS {krs}' if krs else f'"{company}" kontakt'
    ]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for q in queries:
            try:
                r = await c.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={"key": GOOGLE_API_KEY, "cx": GOOGLE_CX, "q": q, "num": 10}
                )
                data = r.json()
                for it in data.get("items", []) or []:
                    u = it.get("link")
                    if u:
                        urls.append(u)
            except Exception as e:
                print("Google API error:", e)
                continue
    seen, uniq = set(), []
    for u in urls:
        if u not in seen:
            uniq.append(u); seen.add(u)
    return uniq[:10]

def choose_official_domain(html: str, url: str, company: str, krs: str):
    if not html:
        return None, None
    text = trafilatura.extract(html) or ""
    low = (text or "").lower()
    n_ok = norm_company(company).lower() in low
    k_ok = (krs and krs in text)
    if not n_ok and not k_ok:
        score = fuzz.partial_ratio(norm_company(company).lower(), low)
        n_ok = score >= 85
    if n_ok or k_ok:
        host = urlparse(url).netloc
        reg = extract_registered_domain(host)
        conf = "wysoka" if k_ok else "średnia"
        return reg, conf
    return None, None

def classify_role(email: str, snippet: str) -> str:
    e = email.lower(); s = snippet.lower()
    if any(x in e or x in s for x in ["zarzad", "zarząd", "secretariat", "sekretariat", "board", "management"]):
        return "Biuro zarządu / sekretariat"
    if "investor" in e or "ir" in e or "investor" in s:
        return "IR / Relacje Inwestorskie"
    if re.search(r"\bit\b", e) or "@it" in e or " it " in s:
        return "IT"
    if "press" in e or "media" in e or "pr@" in e:
        return "PR / Media"
    if any(x in e for x in ["office", "info", "kontakt", "contact"]):
        return "Ogólny kontakt"
    return "Inne/nieokreślone"

def score_confidence(is_mailto: bool, role: str, same_domain: bool) -> float:
    sc = 0.0
    if is_mailto: sc += 0.4
    if role != "Inne/nieokreślone": sc += 0.3
    if same_domain: sc += 0.2
    return min(sc, 0.99)

def snippet_around(haystack: str, needle: str, width=160) -> str:
    hs = haystack
    nlow = needle.lower()
    idx = hs.lower().find(nlow)
    if idx == -1:
        return hs[:width]
    start = max(0, idx - width//2)
    end = min(len(hs), idx + width//2)
    return SPACES_RE.sub(" ", hs[start:end]).strip()

async def crawl_domain(selected_domain: str, client: httpx.AsyncClient):
    base = f"https://{selected_domain}/"
    urls = [base if p == "" else urljoin(base, p) for p in COMMON_PATHS]
    htmls = await asyncio.gather(*(fetch(client, u) for u in urls), return_exceptions=True)

    hits = []
    for url, html in zip(urls, htmls):
        if isinstance(html, Exception) or not html:
            continue
        for enc in CFEMAIL_REGEX.findall(html):
            try:
                decoded = cfemail_decode(enc)
                if decoded and EMAIL_REGEX.fullmatch(decoded):
                    html += f" {decoded} "
            except Exception:
                pass

        soup = BeautifulSoup(html, "html.parser")
        text = deobfuscate_text(soup.get_text(separator=" ", strip=True))

        emails = set(EMAIL_REGEX.findall(html)) | set(EMAIL_REGEX.findall(text))
        mailtos = set(m.group(1) for m in MAILTO_REGEX.finditer(html))

        snap = f"out/pages/{hashlib.md5(url.encode()).hexdigest()}.html"
        try:
            with open(snap, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        for em in sorted(emails):
            is_mailto = em in mailtos
            snip = snippet_around(text, em)
            hits.append({"email": em, "page_url": url, "snippet": snip, "is_mailto": is_mailto})

    best = {}
    for h in hits:
        key = h["email"].lower()
        if key not in best or (h["is_mailto"] and not best[key]["is_mailto"]):
            best[key] = h
    return list(best.values())

async def process_company(entry):
    print(">> processing:", entry)
    company = entry["company"].strip()
    krs = entry.get("krs","").strip()

    result = {
        "company": company,
        "krs": krs,
        "selected_domain": None,
        "domain_confidence": "niska",
        "emails": [],
        "notes": ""
    }

    candidates = await google_candidates(company, krs)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for u in candidates:
            html = await fetch(client, u)
            dom, conf = choose_official_domain(html, u, company, krs)
            if dom:
                result["selected_domain"] = dom
                result["domain_confidence"] = conf
                break
        if not result["selected_domain"]:
            result["notes"] = "Nie udało się potwierdzić oficjalnej domeny."
            return result
        raw_hits = await crawl_domain(result["selected_domain"], client)

    reg_dom = extract_registered_domain(result["selected_domain"])
    enriched = []
    for h in raw_hits:
        email_dom = extract_registered_domain(h["email"].split("@")[-1])
        same_dom = (email_dom == reg_dom)
        role = classify_role(h["email"], h["snippet"])
        conf = score_confidence(h["is_mailto"], role, same_dom)
        enriched.append({
            "email": h["email"],
            "role": role,
            "confidence": round(conf, 2),
            "page_url": h["page_url"],
            "snippet": h["snippet"]
        })
    enriched.sort(key=lambda x: x["confidence"], reverse=True)
    result["emails"] = enriched
    if not enriched:
        result["notes"] = "Nie znaleziono jawnych e-maili."
    return result

async def main():
    print(">> main() start")
    ensure_dirs()

    companies = read_companies("nazwy.txt")
    print(f">> companies loaded: {len(companies)}")

    results = []
    if not companies:
        with open("out/results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        with open("out/results.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["company","krs","selected_domain","domain_confidence","email","role","confidence","page_url","snippet"])
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    async def guarded(entry):
        async with sem:
            return await process_company(entry)

    tasks = [guarded(e) for e in companies]
    for coro in asyncio.as_completed(tasks):
        res = await coro
        print(f"[OK] {res['company']} -> {res['selected_domain'] or '-'} | emails: {len(res['emails'])}")
        results.append(res)

    with open("out/results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open("out/results.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["company","krs","selected_domain","domain_confidence","email","role","confidence","page_url","snippet"])
        for r in results:
            if r["emails"]:
                for e in r["emails"]:
                    w.writerow([r["company"], r["krs"], r["selected_domain"], r["domain_confidence"],
                                e["email"], e["role"], e["confidence"], e["page_url"], e["snippet"]])
            else:
                w.writerow([r["company"], r["krs"], r["selected_domain"], r["domain_confidence"], "", "", "", "", r.get("notes","")])

    print(">> main() done")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        ensure_dirs()
        with open("out/error.txt", "w", encoding="utf-8") as f:
            f.write(str(e))
        raise
