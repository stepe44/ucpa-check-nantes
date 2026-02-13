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
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS_RAW = os.getenv('EMAIL_RECEIVER', '')
EMAIL_RECEIVERS = [r.strip() for r in EMAIL_RECEIVERS_RAW.split(',') if r.strip()]

FREE_SMS_USER = os.getenv('FREE_SMS_USER')
FREE_SMS_PASS = os.getenv('FREE_SMS_PASS')

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS UTILITAIRES ---

def formater_date_relative(date_str):
    """
    Transforme '15/02' en 'Aujourd'hui (Vendredi) 15/02', 
    'Demain (Samedi) 16/02' ou 'Dimanche 17/02'.
    """
    jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    
    try:
        # On extrait jour et mois du format 'JJ/MM'
        jour, mois = map(int, date_str.split('/'))
        # On crée un objet date pour l'année en cours
        date_objet = datetime(maintenant.year, mois, jour)
        
        # Calcul de la différence de jours
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_semaine[date_objet.weekday()]
        
        if diff == 0:
            return f"Aujourd'hui ({nom_jour}) {date_str}"
        elif diff == 1:
            return f"Demain ({nom_jour}) {date_str}"
        else:
            return f"{nom_jour} {date_str}"
    except Exception as e:
        logging.error(f"Erreur formatage date : {e}")
        return date_str

# --- FONCTIONS DE NOTIFICATION ---

def send_whatsapp(message):
    """Envoi via Green API"""
    if not GREEN_API_URL: return
    payload = {"chatId": WHATSAPP_CHAT_ID, "message": message}
    headers = {'Content-Type': 'application/json'}
    try:
        requests.post(GREEN_API_URL, json=payload, headers=headers, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur WhatsApp : {e}")

def send_alerts(course_name, date, time_slot, places):
    """Centralise les alertes (WhatsApp + Email + SMS)"""
    info_places = f"({places} places!)" if places > 0 else ""
    msg_body = f"Cours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}"
    
    # 1. WhatsApp (Formaté avec Markdown)
    send_whatsapp(f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔥 {info_places}\n🔗 {URL_CIBLE}")
    
    # 2. EMAIL
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVERS:
        try:
            msg_mail = MIMEMultipart()
            msg_mail['From'] = f"UCPA Bot <{EMAIL_SENDER}>"
            msg_mail['To'] = ", ".join(EMAIL_RECEIVERS)
            msg_mail['Subject'] = f"🚨 Place Libérée : {course_name} ({date})"
            msg_mail.attach(MIMEText(msg_body, 'plain'))
            
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg_mail)
            logging.info(f"📧 Email envoyé pour {course_name}")
        except Exception as e:
            logging.error(f"❌ Erreur Email : {e}")

    # 3. SMS FREE
    if FREE_SMS_USER and FREE_SMS_PASS:
        msg_sms = f"UCPA : Libre {course_name} le {date} a {time_slot}"
        try:
            requests.get("https://smsapi.free-mobile.fr/sendmsg", 
                         params={'user': FREE_SMS_USER, 'pass': FREE_SMS_PASS, 'msg': msg_sms}, timeout=10)
        except: pass

# --- SCRAPING ET ANALYSE ---

def get_rendered_content(url):
    """Scraping avec rendu JavaScript via Selenium"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(10) # Attente du chargement du planning
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    """Analyse le texte brut pour extraire les cours"""
    if not raw_text: return []
    cours_extraits = []
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

        pattern_cours = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\n(.+?)\n(?:(\d+)\s*places? restantes|Complet)"
        for m in re.finditer(pattern_cours, contenu_jour):
            horaire = m.group(1).split('-')[0].strip()
            nom = m.group(2).strip()
            places = m.group(3)
            
            if COURS_SURVEILLES and not any(mot in nom.lower() for mot in COURS_SURVEILLES):
                continue
                
            cours_extraits.append({
                "nom": nom, "date": date_str, "horaire": horaire,
                "places": int(places) if places else 0,
                "statut": "LIBRE" if places else "COMPLET"
            })
    return cours_extraits

def run_scan():
    logging.info(f"🔍 Démarrage du scan sur : {URL_CIBLE}")
    raw_content = get_rendered_content(URL_CIBLE)
    cours_actuels = analyze_with_regex(raw_content)
    
    if not cours_actuels:
        logging.warning("⚠️ Aucun cours extrait.")
        return

    # Chargement de la mémoire
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except Exception:
            anciens_complets = []

    nouveaux_complets = [c for c in cours_actuels if c['statut'] == "COMPLET"]
    
    # Détection des changements et alertes
    for c in cours_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            # Alerte si le cours était COMPLET au scan précédent
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                
                # Enrichissement de la date pour le message
                date_affichage = formater_date_relative(c['date'])
                send_alerts(c['nom'], date_affichage, c['horaire'], c['places'])

    # Mise à jour de la mémoire
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    logging.info(f"💾 Mémoire mise à jour ({len(nouveaux_complets)} cours complets).")

if __name__ == "__main__":
    try:
        run_scan()
    except Exception as e:
        logging.error(f"Erreur critique : {e}")
