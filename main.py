import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import httpx
import time
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse
import ssl
import socket

# ================================================================
# CONFIG — MODIFIE CES VALEURS
# ================================================================

GOOGLE_SHEETS_ID = "1-YIf4nlUdjrBedal40yqgj4ykVosGhcRnHfibqarlmo"
GOOGLE_CREDS_FILE = "credentials.json"
PAGESPEED_API_KEY = "AIzaSyB5qwT1XUWrYJiGi9ggSS-0ycfwOvaL2wM"

ACTIVITES = [
    "kinesitherapeute",
    "osteopathe",
    "psychologue",
    "sophrologue",
    "hypnotherapeute",
    "naturopathe",
    "coach",
    "therapeute",
    "avocat",
    "coiffeur",
    "estheticienne",
    "auto-ecole",
]

VILLES = [
    "Montpellier",
    "Beziers",
    "Nimes",
    "Perpignan",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ================================================================
# SCRAPING PAGES JAUNES
# ================================================================

def scrape_pages_jaunes(activite, ville, nb_pages=3):
    entreprises = []
    
    for page in range(1, nb_pages + 1):
        url = f"https://www.pagesjaunes.fr/annuaire/chercherlespros?quoiqui={activite}&ou={ville}&page={page}"
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(response.content, "html.parser")
            
            listings = soup.find_all("div", class_="bi-content")
            
            if not listings:
                break
                
            for listing in listings:
                entreprise = {}
                
                # Nom
                nom = listing.find("a", class_="bi-denomination")
                entreprise["nom"] = nom.text.strip() if nom else "N/A"
                
                # Téléphone
                tel = listing.find("a", class_="bi-phone")
                entreprise["telephone"] = tel.text.strip() if tel else "N/A"
                
                # Adresse
                adresse = listing.find("span", class_="bi-address")
                entreprise["adresse"] = adresse.text.strip() if adresse else "N/A"
                
                # Site internet
                site = listing.find("a", class_="bi-website")
                entreprise["site"] = site["href"] if site else None
                
                entreprise["ville"] = ville
                entreprise["activite"] = activite
                
                if entreprise["nom"] != "N/A":
                    entreprises.append(entreprise)
                    
            time.sleep(2)  # Pause pour ne pas se faire bloquer
            
        except Exception as e:
            print(f"Erreur scraping {activite} {ville} page {page}: {e}")
            continue
    
    return entreprises


# ================================================================
# ANALYSE DU SITE
# ================================================================

def verifier_https(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        response = requests.get(url, timeout=5, headers=HEADERS)
        return url.startswith("https://")
    except:
        return False

def verifier_mobile(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy=mobile&key={PAGESPEED_API_KEY}"
        response = requests.get(api_url, timeout=15)
        data = response.json()
        score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score", 0)
        return score * 100 >= 50
    except:
        return False

def get_vitesse(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy=mobile&key={PAGESPEED_API_KEY}"
        response = requests.get(api_url, timeout=15)
        data = response.json()
        fcp = data.get("lighthouseResult", {}).get("audits", {}).get("first-contentful-paint", {}).get("numericValue", 0)
        return round(fcp / 1000, 1)  # en secondes
    except:
        return None

def get_date_maj(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        response = requests.head(url, timeout=5, headers=HEADERS)
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            date = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z")
            return date.strftime("%Y-%m-%d")
        return "Inconnue"
    except:
        return "Inconnue"

def site_repond(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        response = requests.get(url, timeout=5, headers=HEADERS)
        return response.status_code == 200
    except:
        return False

def analyser_site(url):
    if not url:
        return {
            "existe": False,
            "https": False,
            "mobile": False,
            "vitesse": None,
            "date_maj": None,
        }
    
    existe = site_repond(url)
    if not existe:
        return {
            "existe": False,
            "https": False,
            "mobile": False,
            "vitesse": None,
            "date_maj": None,
        }
    
    return {
        "existe": True,
        "https": verifier_https(url),
        "mobile": verifier_mobile(url),
        "vitesse": get_vitesse(url),
        "date_maj": get_date_maj(url),
    }


# ================================================================
# CALCUL DU SCORE
# ================================================================

def calculer_score(entreprise, analyse_site):
    score = 0
    details = []

    # Pas de site du tout
    if not entreprise.get("site"):
        score += 40
        details.append("Pas de site (+40)")
    else:
        if not analyse_site["existe"]:
            score += 35
            details.append("Site mort (+35)")
        else:
            if not analyse_site["https"]:
                score += 15
                details.append("Pas HTTPS (+15)")
            
            if not analyse_site["mobile"]:
                score += 20
                details.append("Pas mobile (+20)")
            
            vitesse = analyse_site.get("vitesse")
            if vitesse and vitesse > 3:
                score += 15
                details.append(f"Site lent {vitesse}s (+15)")
            
            date_maj = analyse_site.get("date_maj")
            if date_maj and date_maj != "Inconnue":
                try:
                    date = datetime.strptime(date_maj, "%Y-%m-%d")
                    annees = (datetime.now() - date).days / 365
                    if annees > 2:
                        score += 20
                        details.append(f"Site vieux {int(annees)}ans (+20)")
                except:
                    pass

    return score, details


def get_priorite(score):
    if score >= 60:
        return "CHAUD"
    elif score >= 30:
        return "MOYEN"
    else:
        return "FROID"


# ================================================================
# GOOGLE SHEETS
# ================================================================

def init_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEETS_ID).sheet1
    return sheet

def init_headers(sheet):
    headers = [
        "Nom", "Téléphone", "Adresse", "Ville", "Activité",
        "Site Internet", "HTTPS", "Mobile Friendly",
        "Vitesse (s)", "Dernière MAJ", "Score", "Priorité", "Détails Score"
    ]
    sheet.update("A1:M1", [headers])
    
    # Style headers
    sheet.format("A1:M1", {
        "backgroundColor": {"red": 0.05, "green": 0.05, "blue": 0.05},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
    })

def ajouter_ligne(sheet, row_num, entreprise, analyse, score, priorite, details):
    site_val = entreprise.get("site") or "AUCUN"
    https_val = "Oui" if analyse["https"] else "Non"
    mobile_val = "Oui" if analyse["mobile"] else "Non"
    vitesse_val = str(analyse["vitesse"]) + "s" if analyse["vitesse"] else "N/A"
    date_val = analyse["date_maj"] or "N/A"

    row = [
        entreprise["nom"],
        entreprise["telephone"],
        entreprise["adresse"],
        entreprise["ville"],
        entreprise["activite"],
        site_val,
        https_val,
        mobile_val,
        vitesse_val,
        date_val,
        score,
        priorite,
        " | ".join(details)
    ]
    
    sheet.update(f"A{row_num}:M{row_num}", [row])

    # Couleur selon priorité
    if priorite == "CHAUD":
        bg = {"red": 0.8, "green": 0.1, "blue": 0.1}
    elif priorite == "MOYEN":
        bg = {"red": 0.9, "green": 0.5, "blue": 0.1}
    else:
        bg = {"red": 0.1, "green": 0.6, "blue": 0.1}

    sheet.format(f"L{row_num}", {"backgroundColor": bg, "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})

    # Cellule rouge si pas de site
    if site_val == "AUCUN":
        sheet.format(f"F{row_num}", {"backgroundColor": {"red": 0.8, "green": 0.1, "blue": 0.1}, "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}}})


# ================================================================
# MAIN
# ================================================================

def main():
    print("Démarrage du script de prospection...")
    
    sheet = init_sheets()
    init_headers(sheet)
    
    row_num = 2
    total = 0
    
    for ville in VILLES:
        for activite in ACTIVITES:
            print(f"Scraping {activite} à {ville}...")
            
            entreprises = scrape_pages_jaunes(activite, ville, nb_pages=2)
            print(f"  {len(entreprises)} entreprises trouvées")
            
            for entreprise in entreprises:
                print(f"  Analyse: {entreprise['nom']}")
                
                analyse = analyser_site(entreprise.get("site"))
                score, details = calculer_score(entreprise, analyse)
                priorite = get_priorite(score)
                
                ajouter_ligne(sheet, row_num, entreprise, analyse, score, priorite, details)
                
                row_num += 1
                total += 1
                
                time.sleep(1)
    
    # Trier par score décroissant
    sheet.sort((11, "des"), range=f"A2:M{row_num}")
    
    print(f"Terminé. {total} entreprises analysées.")
    print(f"Google Sheets mis à jour.")

if __name__ == "__main__":
    main()
