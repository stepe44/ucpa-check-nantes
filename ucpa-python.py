import os
import json
import time
import re
import requests
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'

# --- RÉCUPÉRATION DES SECRETS ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = "33678723278-1540128478@g.us"
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')
FREE_SMS_USER = os.getenv('FREE_SMS_USER')
FREE_SMS_PASS = os.getenv('FREE_SMS_PASS')

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS DE NOTIFICATION ---

def send_whatsapp(message):
    if not GREEN_API_URL:
        logging.error("❌ Secret GREEN_API_URL manquant.")
        return
    payload = {"chatId": WHATSAPP_CHAT_ID, "message": message}
    headers = {'Content-Type': 'application/json'}
    try:
        requests.post(GREEN_API_URL, json=payload, headers=headers, timeout=10)
        logging.info("✅ WhatsApp envoyé")
    except Exception as e:
        logging.error(f"❌ Erreur WhatsApp : {e}")

def send_ntfy(course_name, date, time_slot):
    url = f"https://ntfy.sh/ucpa-nantes-notif-beer-stephane"
    payload = f"Une place s'est libérée pour {course_name} le {date} à {time_slot} !"
    headers = {"Title": "ALERTE UCPA NANTES", "Priority": "5", "Tags": "beer,gym,bell", "Click": URL_CIBLE}
    try:
        requests.post(url, data=payload.encode('utf-8'), headers=headers, timeout=10)
    except: pass

def send_alerts(course_name, date, time_slot):
    msg_wa = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔗 {URL_CIBLE}"
    send_whatsapp(msg_wa)
    send_ntfy(course_name, date, time_slot)
    # ... (Email et SMS restent identiques)

# --- SCRAPING ET ANALYSE (TES VERSIONS OPTIMISÉES) ---

def get_rendered_content(url):
    logging.info(f"🌐 Connexion à : {url}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    # User-agent pour simuler un vrai navigateur
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        logging.info("⏳ Chargement des scripts de la page (10s)...")
        time.sleep(10)
        
        # Scroll pour forcer le rendu des éléments
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    if not raw_text: return []
    
    cours_extraits = []
    maintenant = datetime.now()
    
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)
    logging.info("💾 Artifact 'debug_raw_content.txt' mis à jour.")

    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+(.+?)(?:\s{2,}|\n|$)(.*)"

    sections = re.split(pattern_date, raw_text)
    
    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        mois = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois = (maintenant.month % 12) + 1
            
        date_str = f"{jour_num}/{str(mois).zfill(2)}"
        contenu_jour = sections[i+2]
        
        lignes = contenu_jour.split('\n')
        for ligne in lignes:
            m = re.search(pattern_cours, ligne)
            if m:
                horaire = m.group(1)
                nom = m.group(2).strip()
                reste = m.group(3).lower()
                
                # Filtrage optionnel
                if COURS_SURVEILLES and not any(mot in nom.lower() for mot in COURS_SURVEILLES):
                    continue
                    
                statut = "COMPLET" if "complet" in reste else "LIBRE"
                cours_extraits.append({
                    "nom": nom, "date": date_str, "horaire": horaire, "statut": statut
                })
    return cours_extraits

# --- LOGIQUE PRINCIPALE ---

def run_scan():
    raw_content = get_rendered_content(URL_CIBLE)
    cours_actuels = analyze_with_regex(raw_content)
    
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        with open(MEMO_FILE, 'r', encoding='utf-8') as f:
            anciens_complets = json.load(f)

    nouveaux_complets = [c for c in cours_actuels if c['statut'] == "COMPLET"]
    
    for c in cours_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            # On alerte si ce cours libre était dans la liste "COMPLET" au scan précédent
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                send_alerts(c['nom'], c['date'], c['horaire'])

    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    try:
        run_scan()
    except Exception as e:
        logging.error(f"Erreur run: {e}")
    finally:
        now = datetime.now().strftime("%H:%M:%S")
        send_whatsapp(f"✅ Scan terminé à {now}")
