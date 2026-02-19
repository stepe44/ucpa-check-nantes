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

# --- RÉCUPÉRATION DES SECRETS ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS_RAW = os.getenv('EMAIL_RECEIVER', '')
EMAIL_RECEIVERS = [r.strip() for r in EMAIL_RECEIVERS_RAW.split(',') if r.strip()]
FREE_SMS_USER = os.getenv('FREE_SMS_USER')
FREE_SMS_PASS = os.getenv('FREE_SMS_PASS')

# Filtre de cours (ex: "yoga,pilates")
raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS UTILITAIRES ---

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
    except: return date_str

# --- NOTIFICATIONS ---

def send_whatsapp(message):
    if not GREEN_API_URL: return
    payload = {"chatId": WHATSAPP_CHAT_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur WhatsApp : {e}")

def send_alerts(course_name, date, time_slot, places):
    info_places = f"({places} places!)" if places > 0 else ""
    msg_body = f"Cours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}"
    
    # WhatsApp
    send_whatsapp(f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔥 {info_places}\n🔗 {URL_CIBLE}")
    
    # Email
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
        except Exception as e: logging.error(f"❌ Erreur Email : {e}")

# --- MOTEUR DE SCRAPING ---

def analyze_text_segment(text):
    """Analyse le texte pour extraire les cours avec une regex robuste"""
    cours_extraits = []
    maintenant = datetime.now()
    
    # Découpage par bloc de jour
    start_pattern = r"(\d{2}\s+(?:LUN\.|MAR\.|MER\.|JEU\.|VEN\.|SAM\.|DIM\.))"
    sections = re.split(start_pattern, text)
    
    for i in range(1, len(sections), 2):
        header_jour = sections[i].strip()
        contenu_jour = sections[i+1]
        jour_num = header_jour.split(' ')[0]
        
        mois = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois = (maintenant.month % 12) + 1
        date_str = f"{jour_num}/{str(mois).zfill(2)}"

        # Regex flexible pour gérer "RÉSERVER" ou les variations de sauts de ligne
        pattern_cours = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\n(.+?)\n(?:RÉSERVER\n)?(?:(\d+)\s*places? restantes|Complet)"
        
        for m in re.finditer(pattern_cours, contenu_jour):
            horaire = m.group(1).split('-')[0].strip()
            nom = m.group(2).strip()
            places = m.group(3)
            
            cours_extraits.append({
                "nom": nom, 
                "date": date_str, 
                "horaire": horaire,
                "places": int(places) if places else 0,
                "statut": "LIBRE" if places else "COMPLET"
            })
    return cours_extraits

def get_full_schedule(url):
    """Scraping cumulatif avec scroll progressif pour ne manquer aucun cours"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    
    driver = webdriver.Chrome(options=options)
    all_data = {} # Dictionnaire pour dédoublonner via une clé unique
    
    try:
        logging.info(f"🌐 Ouverture du planning : {url}")
        driver.get(url)
        time.sleep(8) # Attente du chargement initial
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        current_pos = 0
        step = 700 # Pixel par scroll
        
        while current_pos < last_height:
            # Capture du texte à la position actuelle
            text_now = driver.find_element(By.TAG_NAME, "body").text
            found = analyze_text_segment(text_now)
            
            # Stockage avec clé unique (Date+Heure+Nom) pour éviter les doublons du scroll
            for c in found:
                key = f"{c['date']}|{c['horaire']}|{c['nom']}"
                all_data[key] = c
            
            # Scroll
            current_pos += step
            driver.execute_script(f"window.scrollTo(0, {current_pos});")
            time.sleep(1.2)
            last_height = driver.execute_script("return document.body.scrollHeight")
            
        return list(all_data.values())
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return []
    finally:
        driver.quit()

# --- EXECUTION PRINCIPALE ---

def run_scan():
    tous_les_cours = get_full_schedule(URL_CIBLE)
    
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours n'a pu être extrait.")
        return

    # Tri pour le tableau
    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- LOG DU TABLEAU COMPLET ---
    header = f"{'DATE':<6} | {'HEURE':<7} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    separator = "-" * 85
    table_lines = ["", separator, header, separator]
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_suivis_actuels = []

    for c in tous_les_cours:
        # Vérification si le cours est dans la liste surveillée
        est_suivi = any(mot in c['nom'].lower() for mot in COURS_SURVEILLES) if COURS_SURVEILLES else True
        suivi_str = "[X]" if est_suivi else "[ ]"
        
        # Stats
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET":
            stats_jour[c['date']]["complets"] += 1
        
        # Ligne du tableau
        line = f"{c['date']:<6} | {c['horaire']:<7} | {c['statut']:<8} | {c['places']:<3} | {suivi_str:<5} | {c['nom']}"
        table_lines.append(line)
        
        if est_suivi:
            cours_suivis_actuels.append(c)

    table_lines.append(separator)
    logging.info("\n".join(table_lines))

    # --- LOG DU RÉSUMÉ PAR JOUR ---
    logging.info("=== 📊 RÉSUMÉ PAR JOUR ===")
    for jour in sorted(stats_jour.keys()):
        s = stats_jour[jour]
        logging.info(f"📅 {jour} : {s['total']} cours détectés | {s['complets']} cours complets")
    logging.info("==========================")

    # --- GESTION DE LA MÉMOIRE (ALERTES) ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    # On ne garde en mémoire que les cours COMPLET qui font partie de la liste SUIVIE
    nouveaux_complets_suivis = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    
    for c in cours_suivis_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            # Si le cours était COMPLET dans la mémoire précédente
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} le {c['date']} !")
                date_txt = formater_date_relative(c['date'])
                send_alerts(c['nom'], date_txt, c['horaire'], c['places'])

    # Sauvegarde
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets_suivis, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    try:
        run_scan()
    except Exception as e:
        logging.error(f"Erreur critique lors de l'exécution : {e}")
