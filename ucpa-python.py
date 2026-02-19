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
    except Exception: return date_str

# --- NOTIFICATIONS ---

def send_whatsapp(message):
    if not GREEN_API_URL: return
    payload = {"chatId": WHATSAPP_CHAT_ID, "message": message}
    try: requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e: logging.error(f"❌ Erreur WhatsApp : {e}")

def send_alerts(course_name, date, time_slot, places):
    info_places = f"({places} places!)" if places > 0 else ""
    msg_body = f"Cours : {course_name}\nDate : {date}\nHeure : {time_slot}\nLien : {URL_CIBLE}"
    send_whatsapp(f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course_name}*\n📅 {date} à {time_slot}\n🔥 {info_places}\n🔗 {URL_CIBLE}")
    
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

# --- SCRAPING ---

def get_rendered_content(url):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,3000")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        logging.info("🌐 Connexion à l'UCPA...")
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Scroll progressif pour forcer le chargement de tout le tableau
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 800):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.6)
        
        time.sleep(2)
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_all_courses(raw_text):
    """Extrait absolument TOUS les cours présents sur la page"""
    if not raw_text: return []
    cours_liste = []
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
            
            cours_liste.append({
                "nom": nom, 
                "date": date_str, 
                "horaire": horaire,
                "places": int(places) if places else 0,
                "statut": "LIBRE" if places else "COMPLET"
            })
    return cours_liste

def run_scan():
    raw_content = get_rendered_content(URL_CIBLE)
    tous_les_cours = analyze_all_courses(raw_content)
    
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours détecté. Vérifiez le rendu de la page.")
        return

    # --- GÉNÉRATION DU TABLEAU DE LOG ---
    header = f"{'DATE':<8} | {'HEURE':<7} | {'STATUT':<8} | {'PLACES':<4} | {'SUIVI':<5} | {'NOM DU COURS'}"
    separator = "-" * 90
    
    table_lines = [header, separator]
    
    cours_a_surveiller = []
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})

    for c in tous_les_cours:
        est_suivi = any(mot in c['nom'].lower() for mot in COURS_SURVEILLES) if COURS_SURVEILLES else True
        suivi_str = "OUI" if est_suivi else "non"
        
        # Stats pour le résumé
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET":
            stats_jour[c['date']]["complets"] += 1
        
        # Ajout à la ligne du tableau
        line = f"{c['date']:<8} | {c['horaire']:<7} | {c['statut']:<8} | {c['places']:<6} | {suivi_str:<5} | {c['nom']}"
        table_lines.append(line)
        
        # On ne garde pour la suite que les cours suivis
        if est_suivi:
            cours_a_surveiller.append(c)

    # Affichage du grand tableau
    logging.info("\n" + "\n".join(table_lines) + "\n")

    # Petit résumé par jour
    logging.info("=== 📈 RÉSUMÉ QUOTIDIEN ===")
    for jour, s in sorted(stats_jour.items()):
        logging.info(f"📅 {jour} : {s['total']} cours détectés ({s['complets']} complets)")
    logging.info("===========================")

    # --- LOGIQUE D'ALERTE (Mémoire) ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: anciens_complets = []

    nouveaux_complets = [c for c in cours_a_surveiller if c['statut'] == "COMPLET"]
    
    for c in cours_a_surveiller:
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
