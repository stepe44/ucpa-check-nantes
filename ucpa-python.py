import os
import json
import time
import re
import requests
import logging
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'

# --- RÉCUPÉRATION DES SECRETS (Inchangé) ---
# GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS_RAW = os.getenv('EMAIL_RECEIVER', '')
EMAIL_RECEIVERS = [r.strip() for r in EMAIL_RECEIVERS_RAW.split(',') if r.strip()]
FREE_SMS_USER = os.getenv('FREE_SMS_USER')
FREE_SMS_PASS = os.getenv('FREE_SMS_PASS')

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS UTILITAIRES (Inchangé) ---

def formater_date_relative(date_str):
    jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        date_objet = datetime(maintenant.year, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_semaine[date_objet.weekday()]
        if diff == 0: return f"Aujourd'hui ({nom_jour}) {date_str}"
        elif diff == 1: return f"Demain ({nom_jour}) {date_str}"
        else: return f"{nom_jour} {date_str}"
    except Exception: return date_str

# --- FONCTIONS DE NOTIFICATION (Inchangé) ---

def send_whatsapp(message):
    if not GREEN_API_URL: return
    payload = {"chatId": WHATSAPP_CHAT_ID, "message": message}
    try: requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except: pass

def send_alerts(course_name, date, time_slot, places):
    info_places = f"({places} places!)" if places > 0 else ""
    msg_body = f"Cours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}"
    send_whatsapp(f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔥 {info_places}\n🔗 {URL_CIBLE}")
    # ... (Email et SMS restent identiques)

# --- NOUVELLE LOGIQUE DE RÉCUPÉRATION ---

def get_rendered_content(url):
    """Scraping avec scroll progressif pour forcer le chargement du planning complet"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,3000") # Fenêtre haute pour voir plus d'éléments
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        logging.info("🌐 Ouverture de la page...")
        driver.get(url)
        
        # Attente initiale que le planning soit présent
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        logging.info("🖱️ Début du défilement progressif...")
        
        # Scroll par étapes de 800 pixels pour déclencher le Lazy Loading
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            # Scroll progressif
            for i in range(0, last_height, 800):
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.5) 
            
            time.sleep(2) # Attendre que les nouveaux éléments se chargent
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break # On a atteint le bas de la page
            last_height = new_height
            logging.info(f"   ∟ Page étendue à {new_height}px, on continue de descendre...")

        # Un dernier scroll vers le haut pour s'assurer que tout est bien rendu
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

# --- ANALYSE ET LOGS (Inchangé mais crucial pour tes stats) ---

def analyze_with_regex(raw_text):
    if not raw_text: return [], {}
    cours_extraits = []
    stats_detectes_par_jour = defaultdict(int)
    maintenant = datetime.now()
    
    start_pattern = r"(\d{2}\s+(?:LUN\.|MAR\.|MER\.|JEU\.|VEN\.|SAM\.|DIM\.))"
    sections = re.split(start_pattern, raw_text)
    
    for i in range(1, len(sections), 2):
        header_jour = sections[i].strip()
        contenu_jour = sections[i+1]
        jour_num = header_jour.split(' ')[0]
        mois = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois = (maintenant.month % 12) + 1
        date_str = f"{jour_num}/{str(mois).zfill(2)}"

        # Regex adaptée pour capturer le texte même avec des sauts de ligne variés
        pattern_cours = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\n(.+?)\n(?:(\d+)\s*places? restantes|Complet)"
        for m in re.finditer(pattern_cours, contenu_jour):
            horaire = m.group(1).split('-')[0].strip()
            nom = m.group(2).strip()
            places = m.group(3)
            
            stats_detectes_par_jour[date_str] += 1
            
            if COURS_SURVEILLES and not any(mot in nom.lower() for mot in COURS_SURVEILLES):
                continue
                
            cours_extraits.append({
                "nom": nom, "date": date_str, "horaire": horaire,
                "places": int(places) if places else 0,
                "statut": "LIBRE" if places else "COMPLET"
            })
    return cours_extraits, stats_detectes_par_jour

def run_scan():
    logging.info(f"🔍 Scan lancé sur : {URL_CIBLE}")
    raw_content = get_rendered_content(URL_CIBLE)
    cours_actuels, stats_globales = analyze_with_regex(raw_content)
    
    if not stats_globales:
        logging.warning("⚠️ Aucun cours trouvé sur la page (problème de chargement ?)")
        return

    # --- LOGS DES STATISTIQUES ---
    logging.info("=== 📊 RÉSUMÉ DU CHARGEMENT PAR JOUR ===")
    total_general = 0
    for jour in sorted(stats_globales.keys()):
        nb = stats_globales[jour]
        total_general += nb
        complets = [c for c in cours_actuels if c['date'] == jour and c['statut'] == "COMPLET"]
        noms_complets = [f"{c['nom']} ({c['horaire']})" for c in complets]
        
        logging.info(f"📅 {jour} : {nb} cours détectés au total.")
        if noms_complets:
            logging.info(f"   ∟ 🔴 Cours complets (surveillés) : {', '.join(noms_complets)}")
        else:
            logging.info(f"   ∟ ✅ Aucun cours complet parmi tes favoris.")
    
    logging.info(f"📈 TOTAL : {total_general} cours scrapés sur toute la semaine.")
    logging.info("==========================================")

    # ... (La suite de la logique de mémoire reste identique)
    # Chargement de la mémoire
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except Exception: anciens_complets = []

    nouveaux_complets = [c for c in cours_actuels if c['statut'] == "COMPLET"]
    
    for c in cours_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c['nom'], formater_date_relative(c['date']), c['horaire'], c['places'])

    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    try: run_scan()
    except Exception as e: logging.error(f"Erreur critique : {e}")

