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

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS UTILITAIRES ---

def formater_date_relative(date_str):
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    try:
        j, m = map(int, date_str.split('/'))
        date_obj = datetime(maintenant.year, m, j)
        diff = (date_obj.date() - maintenant.date()).days
        return f"{jours[date_obj.weekday()]} {date_str}"
    except: return date_str

def send_alerts(course):
    date_txt = formater_date_relative(course['date'])
    msg = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course['nom']}*\n📅 {date_txt}\n⏰ {course['horaire']}\n🔥 {course['places']} places!\n🔗 {URL_CIBLE}"
    if GREEN_API_URL:
        try: requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg}, timeout=10)
        except: pass
    if EMAIL_SENDER and EMAIL_PASSWORD:
        try:
            m = MIMEMultipart()
            m['Subject'] = f"🚨 Place UCPA : {course['nom']}"
            m.attach(MIMEText(msg.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.send_message(m)
        except: pass

# --- MOTEUR DE SCRAPING CUMULATIF ---

def extract_from_raw(text):
    """Analyse un segment de texte pour en extraire les cours"""
    found = []
    maintenant = datetime.now()
    # Découpage par jour
    sections = re.split(r"(\d{2}\s+(?:LUN\.|MAR\.|MER\.|JEU\.|VEN\.|SAM\.|DIM\.))", text)
    for i in range(1, len(sections), 2):
        jour_num = sections[i].strip().split(' ')[0]
        m_val = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20: m_val = (m_val % 12) + 1
        date_cle = f"{jour_num}/{str(m_val).zfill(2)}"
        
        # Pattern robuste pour capturer l'horaire et le nom même si séparés par du JS
        # Cherche l'horaire, puis le texte suivant jusqu'au statut de place
        pattern = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\n(.*?)\n(?:.*?)(?:(\d+)\s*places? restantes|Complet)"
        for match in re.finditer(pattern, sections[i+1], re.DOTALL):
            h = match.group(1).strip()
            nom = match.group(2).strip().split('\n')[0]
            p = match.group(3)
            found.append({
                "nom": nom, "date": date_cle, "horaire": h,
                "places": int(p) if p else 0,
                "statut": "LIBRE" if p else "COMPLET"
            })
    return found

def get_infinity_scroll_data(url):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("window-size=1920,1080")
    dr = webdriver.Chrome(options=options)
    catalog = {}
    raw_debug_accumulator = ""

    try:
        logging.info("🌐 Connexion à l'UCPA (Interpretation JS locale)...")
        dr.get(url)
        wait = WebDriverWait(dr, 20)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        last_h = 0
        current_pos = 0
        step = 350 # Scroll court pour ne rien sauter

        while True:
            # Capture du texte à la position actuelle
            current_text = dr.find_element(By.TAG_NAME, "body").text
            raw_debug_accumulator += f"\n--- STEP AT {current_pos}px ---\n{current_text}"
            
            for c in extract_from_raw(current_text):
                # ID Unique pour fusionner les captures
                key = f"{c['date']}|{c['horaire']}|{c['nom']}"
                catalog[key] = c
            
            # Scroll vers le bas
            current_pos += step
            dr.execute_script(f"window.scrollTo(0, {current_pos});")
            time.sleep(1.5) # Attente interprétation JS local
            
            new_h = dr.execute_script("return document.body.scrollHeight")
            if current_pos > new_h or current_pos > 5000: # Sécurité fin de page
                break
        
        # Artifact Debug
        print("\n" + "="*20 + " SOURCE RAW POUR DEBUG " + "="*20)
        print(raw_debug_accumulator[:5000] + "... [TRUNCATED]") # On affiche un extrait du debug
        print("="*60 + "\n")
        
        return list(catalog.values())
    finally: dr.quit()

# --- LOGIQUE PRINCIPALE ---

def run():
    cours = get_infinity_scroll_data(URL_CIBLE)
    if not cours: return

    cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- TABLEAU DE LOG ---
    print(f"\n{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}")
    print("-" * 100)
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_suivis = []

    for c in cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET": stats_jour[c['date']]["complets"] += 1
        
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi: cours_suivis.append(c)

    print("-" * 100)
    for j, s in sorted(stats_jour.items()):
        logging.info(f"📊 {j} : {s['total']} cours détectés | {s['complets']} complets")

    # --- MÉMOIRE ET ALERTES ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try: anciens_complets = json.load(open(MEMO_FILE, 'r', encoding='utf-8'))
        except: pass

    for c in cours_suivis:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c
