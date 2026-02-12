import os
import json
import time
import re
import requests
import logging
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# --- CONFIGURATION LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- VARIABLES D'ENVIRONNEMENT ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def send_whatsapp(message):
    if not GREEN_API_URL or not WHATSAPP_ID: return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Lancement du navigateur pour : {url}")
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"})
        driver.get(url)
        
        # Scroll progressif pour forcer le chargement du JS UCPA
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.4)
            
        # Attente que les données de créneaux soient visibles
        try:
            WebDriverWait(driver, 15).until(
                lambda d: "####" in d.find_element(By.TAG_NAME, "body").text
            )
        except:
            pass
            
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    """
    Analyse le texte brut UCPA par blocs de jours.
    Extrait le nom du cours via les marqueurs '####' et l'heure via le pattern '*'
    """
    cours_extraits = []
    maintenant = datetime.now()
    
    # Étape 1 : Découper par jour (ex: "09 lun.", "10 mar.")
    # On cherche 2 chiffres suivis d'un jour abrégé
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    
    # Étape 2 : Pattern pour capturer un cours
    # Groupe 1: Heure | Groupe 2: Nom du cours | Groupe 3: Statut/Reste
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ ].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    # Re-split donne une liste : [texte_avant, "09", "lun.", texte_apres, "10", "mar.", ...]
    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        
        # Logique simple de gestion de mois (si jour extrait < jour actuel, on passe probablement au mois suivant)
        mois_objet = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois_objet = (maintenant.month % 12) + 1
        
        date_str = f"{jour_num}/{str(mois_objet).zfill(2)}"
        contenu_du_jour = sections[i+2]
        
        matches = re.finditer(pattern_cours, contenu_du_jour)
        for m in matches:
            horaire = m.group(1).replace(' ', '')
            nom = m.group(2).strip()
            indicateur_statut = m.group(3).lower()
            
            statut = "COMPLET" if "complet" in indicateur_statut else "LIBRE"
            
            cours_extraits.append({
                "nom": nom,
                "date": date_str,
                "horaire": horaire,
                "statut": statut
            })
            
    return cours_extraits

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT (MOTEUR REGEX) ---")
    raw = get_heavy_selenium_content(URL_CIBLE)
    
    if not raw or "####" not in raw:
        logging.warning("⚠️ Données UCPA non détectées dans le texte brut.")
        return

    cours = analyze_with_regex(raw)
    
    if not cours:
        logging.warning("⚠️ Aucun cours trouvé après analyse Regex.")
        return

    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: 
                anciens_complets = json.load(f)
            except: 
                pass

    maintenant = datetime.now()
    aujourdhui_date = maintenant.date()
    heure_limite = maintenant - timedelta(minutes=30)

    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 70)

    for c in cours:
        nom = c['nom']
        d_raw = c['date']
        h_raw = c['horaire']
        statut = c['statut']

        try:
            parts = d_raw.split('/')
            # On suppose l'année actuelle
            date_objet = datetime(maintenant.year, int(parts[1]), int(parts[0])).date()
            
            h_clean = h_raw.lower().replace('h', ':').strip()
            hh, mm = map(int, h_clean.split(':'))
            datetime_cours = datetime(maintenant.year, int(parts[1]), int(parts[0]), hh, mm)

            # Filtres temporels
            if date_objet < aujourdhui_date: continue
            if date_objet == aujourdhui_date and datetime_cours < heure_limite: continue
        except Exception as e:
            logging.debug(f"Erreur parsing {nom}: {e}")
            continue

        if statut == "COMPLET":
            nouveaux_complets.append(c)
            icon = "🔴"
        else:
            icon = "🟢"
            # Détection de libération
            etait_complet = any(
                a.get('nom','').strip().lower() == nom.lower() and 
                a.get('date') == d_raw and 
                a.get('horaire') == h_raw
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)
                icon = "🚨"

        print(f"{icon} {statut:<8} | {d_raw:<6} | {h_raw:<10} | {nom}")

    # Envoi des alertes WhatsApp
    if alertes:
        for c in alertes:
            msg = f"🚨 LIBRE : {c['nom']}\n📅 {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
            logging.info(f"📱 Alerte envoyée pour {c['nom']}")

    # Sauvegarde de la mémoire (uniquement les complets)
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info(f"🏁 Scan fini. {len(cours)} cours analysés, {len(nouveaux_complets)} complets.")

if __name__ == "__main__":
    run_scan()
