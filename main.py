def read_companies(path="nazwy.txt"):
    if not Path(path).exists():
        raise FileNotFoundError("Brak pliku nazwy.txt (każda linia: 'Pełna nazwa | KRS' lub 'Pełna nazwa;KRS' albo samo 'Pełna nazwa').")

    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Obsługa dwóch separatorów: '|' lub ';'
            if "|" in line:
                name, krs = [x.strip() for x in line.split("|", 1)]
            elif ";" in line:
                name, krs = [x.strip() for x in line.split(";", 1)]
            else:
                name, krs = line, ""  # tylko nazwa, bez KRS

            rows.append({"company": name, "krs": krs})
    return rows
