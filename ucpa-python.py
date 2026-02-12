import os
import json
import time
import re
import requests
import logging
import smtplib
import subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'
WHATSAPP_GROUP_ID = "120363425102471283@g.us"

# --- RÉCUPÉRATION DES SETTINGS ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')
FREE_SMS_USER = os.getenv('FREE_SMS_USER')
FREE_SMS_PASS = os.getenv('FREE_SMS_PASS')

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

def send_ntfy(course_name, date, time_slot):
    topic = "ucpa-nantes-notif-beer-stephane"
    url = f"https://ntfy.sh/{topic}"
    payload = f"Une place s'est libérée pour {course_name} le {date} à {time_slot} !"
    headers = {"Title": "ALERTE UCPA NANTES", "Priority": "5", "Tags": "beer,gym,bell", "Click": URL_CIBLE}
    try:
        requests.post(url, data=payload.encode('utf-8'), headers=headers, timeout=10)
        logging.info(f"🔔 ntfy envoyé : {course_name}")
    except Exception as e:
        logging.error(f"❌ Erreur ntfy : {e}")

def send_alerts(course_name, date, time_slot):
    alert_text = f"PLACE LIBRE : {course_name} le {date} à {time_slot}"
    
    # 1. WhatsApp via MUDSLIDE (Groupe)
    msg_wa = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔗 {URL_CIBLE}"
    try:
        # Utilisation de subprocess pour appeler la commande système mudslide
        subprocess.run(['mudslide', 'send', WHATSAPP_GROUP_ID, msg_wa], check=True)
        logging.info(f"✅ WhatsApp Mudslide envoyé au groupe {WHATSAPP_GROUP_ID}")
    except Exception as e:
        logging.error(f"❌ Erreur Mudslide : {e}")

    # 2. WhatsApp via GREEN API (Optionnel)
    if GREEN_API_URL and WHATSAPP_ID:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_ID, "message": msg_wa}, timeout=10)
        except Exception: pass

    # 3. NTFY
    send_ntfy(course_name, date, time_slot)    
    
    # 4. SMS FREE (Correction encodage)
    if FREE_SMS_USER and FREE_SMS_PASS:
        params = {'user': FREE_SMS_USER, 'pass': FREE_SMS_PASS, 'msg': f"UCPA : {alert_text}"}
        try:
            requests.get("https://smsapi.free-mobile.fr/sendmsg", params=params, timeout=10)
            logging.info(f"📲 SMS Free envoyé")
        except Exception as e:
            logging.error(f"❌ Erreur SMS : {e}")
    
    # 5. EMAIL
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
        msg_mail = MIMEMultipart()
        msg_mail['From'] = f"UCPA Bot <{EMAIL_SENDER}>"; msg_mail['To'] = EMAIL_RECEIVER; msg_mail['Subject'] = f"🚨 Place Libérée : {course_name}"
        msg_mail.attach(MIMEText(f"Cours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}", 'plain'))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls(); server.login(EMAIL_SENDER, EMAIL_PASSWORD); server.send_message(msg_mail)
            logging.info(f"📧 Email envoyé")
        except Exception as e:
            logging.error(f"❌ Erreur Email : {e}")

def get_heavy_selenium_content(url):
    options = Options()
    options.add_argument("--headless=new"); options.add_argument("--no-sandbox"); options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(5) # Laisser charger
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}"); return ""
    finally:
        driver.quit()

def analyze_vertical_data(raw_text):
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    cours_extraits = []
    current_day_num = None
    jours_semaine = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
    maintenant = datetime.now()

    for i in range(len(lines)):
        ligne = lines[i]
        if ligne.lower() in jours_semaine:
            if i + 1 < len(lines) and lines[i+1].isdigit():
                current_day_num = lines[i+1].zfill(2)
                continue
        if re.match(r"\d{1,2}h\d{2}\s*-\s*\d{1,2}h\d{2}", ligne):
            if current_day_num:
                nom_cours = lines[i-1]
                if COURS_SURVEILLES and not any(mot in nom_cours.lower() for mot in COURS_SURVEILLES):
                    continue
                statut_brut = lines[i+1] if i + 1 < len(lines) else ""
                statut = "COMPLET" if "complet" in statut_brut.lower() else "LIBRE"
                cours_extraits.append({"nom": nom_cours, "date": f"{current_day_num}/{str(maintenant.month).zfill(2)}", "horaire": ligne.split('-')[0].strip(), "statut": statut})
    return cours_extraits

def send_test_heartbeat():
    """Notification de fin d'exécution envoyée à chaque fois"""
    now = datetime.now().strftime("%H:%M:%S")
    msg = f"✅ Fin de scan UCPA à {now}. Status: OK."
    logging.info("🚀 Envoi du Heartbeat de test...")
    # Test Mudslide
    subprocess.run(['mudslide', 'send', WHATSAPP_GROUP_ID, msg])
    # Test ntfy
    send_ntfy("SYSTÈME", "Aujourd'hui", now)

def run_scan():
    raw_content = get_heavy_selenium_content(URL_CIBLE)
    if not raw_content: return
    cours_actuels = analyze_vertical_data(raw_content)
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        with open(MEMO_FILE, 'r', encoding='utf-8') as f:
            anciens_complets = json.load(f)

    nouveaux_complets = [c for c in cours_actuels if c['statut'] == "COMPLET"]
    for c in cours_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                send_alerts(c['nom'], c['date'], c['horaire'])

    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    try: # Correction de la SyntaxError
        run_scan()
    except Exception as e:
        logging.error(f"Erreur run: {e}")
    finally:
        send_test_heartbeat()
        
