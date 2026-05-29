import csv
import re
import unicodedata
import io
from flask import Flask, render_template, request, send_file
import requests
from pathlib import Path

app = Flask(__name__)

# ========================
# Pobieranie list z API GOV
# ========================

def pobierz_liste_z_api(url, cache_file):
    """Pobiera CSV z API i zwraca set imion/nazwisk"""
    cache_path = Path(cache_file)
    
    # Jeśli cache istnieje, wczytaj
    if cache_path.exists():
        with open(cache_path, 'r', encoding='utf-8') as f:
            return set(line.strip().lower() for line in f if line.strip())
    
    # Pobierz z API
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        content = response.content.decode('utf-8')
        lines = content.strip().split('\n')
        
        # Pierwsza kolumna to imiona/nazwiska
        result = set()
        for line in lines[1:]:  # pomiń nagłówek
            parts = line.split(',')
            if parts:
                value = parts[0].strip().lower()
                if value:
                    result.add(value)
        
        # Zapisz cache
        with open(cache_path, 'w', encoding='utf-8') as f:
            for item in result:
                f.write(item + '\n')
        
        return result
    except Exception as e:
        print(f"Błąd pobierania {url}: {e}")
        return set()

# URL z API GOV
URL_FEMALE_NAMES = "https://api.dane.gov.pl/resources/1159670,lista-imion-zenskich-w-rejestrze-pesel-stan-na-20012026-imie-pierwsze/csv"
URL_MALE_NAMES = "https://api.dane.gov.pl/resources/1159669,lista-imion-meskich-w-rejestrze-pesel-stan-na-20012026-imie-pierwsze/csv"
URL_FEMALE_SURNAMES = "https://api.dane.gov.pl/resources/1148811,nazwiska-zenskie-stan-na-2026-01-20/csv"
URL_MALE_SURNAMES = "https://api.dane.gov.pl/resources/1148808,nazwiska-meskie-stan-na-2026-01-20/csv"

# Wczytanie list (z cache)
print("Pobieram listy imion i nazwisk (może potrwać chwilę przy pierwszym uruchomieniu)...")
female_names = pobierz_liste_z_api(URL_FEMALE_NAMES, "cache_female_names.txt")
male_names = pobierz_liste_z_api(URL_MALE_NAMES, "cache_male_names.txt")
female_surnames = pobierz_liste_z_api(URL_FEMALE_SURNAMES, "cache_female_surnames.txt")
male_surnames = pobierz_liste_z_api(URL_MALE_SURNAMES, "cache_male_surnames.txt")

print(f"Załadowano: {len(female_names)} imion żeńskich, {len(male_names)} imion męskich")
print(f"Załadowano: {len(female_surnames)} nazwisk żeńskich, {len(male_surnames)} nazwisk męskich")

# ========================
# Logika określania płci
# ========================

def usun_diakrytyki(tekst):
    return ''.join(
        c for c in unicodedata.normalize('NFD', tekst)
        if unicodedata.category(c) != 'Mn'
    ).lower()

def segmenty_z_emaila(email):
    if not email or '@' not in email:
        return []
    local_part = email.split('@')[0].lower()
    local_part = re.sub(r'[^a-ząćęłńóśźż.]', '', local_part)
    segments = re.split(r'[._\-]', local_part)
    return [s for s in segments if len(s) >= 3]

def okresl_plec(firstname, email):
    # Priorytet 1: Imię
    if firstname and firstname.strip():
        imie = firstname.strip().lower()
        imie_normalized = usun_diakrytyki(imie)
        
        if imie in female_names or imie_normalized in female_names:
            return 'female'
        if imie in male_names or imie_normalized in male_names:
            return 'men'
    
    # Priorytet 2: E-mail
    if email:
        segments = segmenty_z_emaila(email)
        for seg in segments:
            seg_normalized = usun_diakrytyki(seg)
            if seg in female_names or seg_normalized in female_names:
                return 'female'
            if seg in male_names or seg_normalized in male_names:
                return 'men'
            
            # Sprawdź nazwiska (ostatnia deska)
            if seg in female_surnames:
                return 'female'
            if seg in male_surnames:
                return 'men'
    
    return ''

# ========================
# Flask routes
# ========================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_file():
    if 'file' not in request.files:
        return 'Brak pliku', 400
    
    file = request.files['file']
    if file.filename == '':
        return 'Nie wybrano pliku', 400
    
    # Wczytaj CSV
    content = file.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    
    # Sprawdź wymagane kolumny
    required_cols = {'email', 'firstname'}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        return f'Brak wymaganych kolumn. Potrzebuję: {required_cols}', 400
    
    # Przetwarzaj wiersze
    rows = []
    for row in reader:
        firstname = row.get('firstname', '') or ''
        email = row.get('email', '') or ''
        row['sex'] = okresl_plec(firstname, email)
        rows.append(row)
    
    # Przygotuj plik wyjściowy
    output = io.StringIO()
    fieldnames = reader.fieldnames + ['sex']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    
    # Zwróć plik
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='klienci_z_plcia.csv'
    )

if __name__ == '__main__':
    app.run(debug=True)