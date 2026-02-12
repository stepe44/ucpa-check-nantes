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
from selenium.webdriver.support.ui import WebDriverWait

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'

# --- RÉCUPÉRATION DES SETTINGS (GitHub Secrets/Vars) ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER')

# Lecture de la liste de filtrage depuis les paramètres
raw_filter = os.getenv('COURS_SURVEILLES', '')
if raw_filter:
    # On transforme "Yoga, Biking" en ["yoga", "biking"]
    COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()]
else:
    COURS_SURVEILLES = []

def send_alerts(course_name, date, time_slot):
    """Envoie les alertes WhatsApp et Email"""
    # WhatsApp
    if GREEN_API_URL and WHATSAPP_ID:
        msg_wa = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔗 {URL_CIBLE}"
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_ID, "message": msg_wa}, timeout=10)
        except Exception: pass

    # Email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER:
        msg_mail = MIMEMultipart()
        msg_mail['From'] = f"UCPA Bot <{EMAIL_SENDER}>"
        msg_mail['To'] = EMAIL_RECEIVER
        msg_mail['Subject'] = f"🚨 Place Libérée : {course_name}"
        body = f"Une place est disponible !\n\nCours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}"
        msg_mail.attach(MIMEText(body, 'plain'))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg_mail)
            logging.info(f"📧 Email envoyé pour {course_name}")
        except Exception as e:
            logging.error(f"❌ Erreur Email : {e}")

def get_heavy_selenium_content(url):
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
        driver.get(url)
        
        # Scroll progressif
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.5)
        
        WebDriverWait(driver, 25).until(lambda d: "complet" in d.find_element(By.TAG_NAME, "body").text.lower() or "réserver" in d.find_element(By.TAG_NAME, "body").text.lower())
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_vertical_data(raw_text):
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)

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
                
                # --- LOGIQUE DE FILTRAGE DYNAMIQUE ---
                if COURS_SURVEILLES:
                    if not any(mot in nom_cours.lower() for mot in COURS_SURVEILLES):
                        continue

                statut_brut = ""
                if i + 1 < len(lines):
                    if "RÉSERVER" in lines[i+1].upper():
                        statut_brut = lines[i+2] if i + 2 < len(lines) else ""
                    else:
                        statut_brut = lines[i+1]

                statut = "COMPLET" if "complet" in statut_brut.lower() else "LIBRE"
                mois = maintenant.month
                if int(current_day_num) < maintenant.day and maintenant.day > 25:
                    mois = (maintenant.month % 12) + 1
                
                cours_extraits.append({
                    "nom": nom_cours,
                    "date": f"{current_day_num}/{str(mois).zfill(2)}",
                    "horaire": ligne.split('-')[0].strip(),
                    "statut": statut
                })
    return cours_extraits

def run_scan():
    raw_content = get_heavy_selenium_content(URL_CIBLE)
    if not raw_content: return

    cours_actuels = analyze_vertical_data(raw_content)
    
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    nouveaux_complets = []
    
    print(f"\n--- SURVEILLANCE ({'FILTRÉE' if COURS_SURVEILLES else 'TOTALE'}) ---")
    for c in cours_actuels:
        id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
        if c['statut'] == "COMPLET":
            nouveaux_complets.append(c)
            print(f"🔴 | {c['date']} | {c['horaire']} | {c['nom']}")
        else:
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets)
            if etait_complet:
                send_alerts(c['nom'], c['date'], c['horaire'])
                print(f"🚨 | {c['date']} | {c['horaire']} | {c['nom']} (ALERTÉ !)")
            else:
                print(f"🟢 | {c['date']} | {c['horaire']} | {c['nom']}")

    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run_scan()
