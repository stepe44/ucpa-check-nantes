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
        nom = jours[date_obj.weekday()]
        if diff == 0: return f"Aujourd'hui ({nom}) {date_str}"
        if diff == 1: return f"Demain ({nom}) {date_str}"
        return f"{nom} {date_str}"
    except: return date_str

def send_alerts(course):
    """Notification centralisée"""
    date_txt = formater_date_relative(course['date'])
    msg = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course['nom']}*\n📅 {date_txt}\n⏰ {course['horaire']}\n🔥 {course['places']} places!\n🔗 {URL_CIBLE}"
    
    # WhatsApp
    if GREEN_API_URL:
        try: requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg}, timeout=10)
        except Exception as e: logging.error(f"Erreur WhatsApp: {e}")
    
    # Email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVERS:
        try:
            m = MIMEMultipart()
            m['From'] = f"UCPA Bot <{EMAIL_SENDER}>"
            m['To'] = ", ".join(EMAIL_RECEIVERS)
            m['Subject'] = f"🚨 Place Libérée : {course['nom']} ({course['date']})"
            m.attach(MIMEText(msg.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.send_message(m)
            logging.info(f"📧 Email envoyé pour {course['nom']}")
        except Exception as e: logging.error(f"❌ Erreur Email : {e}")

# --- MOTEUR DE SCRAPING HAUTE PRÉCISION ---

def extraire_cours_du_texte(text):
    """Analyse par blocs horaires pour capturer les doublons et simultanés"""
    found_courses = []
    maintenant = datetime.now()
    
    # 1. Séparation par jour (ex: 20 VEN.)
    sections_jours = re.split(r"(\d{2}\s+(?:LUN\.|MAR\.|MER\.|JEU\.|VEN\.|SAM\.|DIM\.))", text)
    
    for i in range(1, len(sections_jours), 2):
        jour_brut = sections_jours[i].strip().split(' ')[0]
        bloc_jour = sections_jours[i+1]
        
        m_val = maintenant.month
        if int(jour_brut) < maintenant.day and maintenant.day > 20: m_val = (m_val % 12) + 1
        date_cle = f"{jour_brut}/{str(m_val).zfill(2)}"

        # 2. Découpage par heure pour isoler chaque carte d'activité
        pattern_heure = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})"
        blocs_horaires = re.split(pattern_heure, bloc_jour)
        
        for j in range(1, len(blocs_horaires), 2):
            horaire = blocs_horaires[j].strip()
            details = blocs_horaires[j+1].strip()
            
            # Extraction du nom (première ligne de texte après l'heure)
            lignes = [l.strip() for l in details.split('\n') if l.strip()]
            if not lignes: continue
            nom = lignes[0]
            
            # Détection places / complet
            p_match = re.search(r"(\d+)\s*places? restantes", details)
            est_complet = "Complet" in details
            
            p_val = int(p_match.group(1)) if p_match else 0
            statut = "LIBRE" if p_val > 0 else "COMPLET" if est_complet else None

            if statut:
                found_courses.append({
                    "nom": nom, "date": date_cle, "horaire": horaire,
                    "places": p_val, "statut": statut
                })
    return found_courses

def get_data():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("window-size=1920,2500") # Fenêtre large et haute
    dr = webdriver.Chrome(options=opts)
    
    catalog = {} 
    try:
        logging.info("🌐 Lancement du scan cumulatif (scroll 200px)...")
        dr.get(URL_CIBLE)
        time.sleep(12) # Attente chargement initial
        
        h_max = dr.execute_script("return document.body.scrollHeight")
        pos = 0
        while pos < h_max:
            # Capture et fusion
            txt = dr.find_element(By.TAG_NAME, "body").text
            for c in extraire_cours_du_texte(txt):
                # Clé unique pour différencier les cours à la même heure
                key = f"{c['date']}|{c['horaire']}|{c['nom']}"
                catalog[key] = c
            
            pos += 200 # Pas de scroll court pour forcer le rendu de chaque carte
            dr.execute_script(f"window.scrollTo(0, {pos});")
            time.sleep(1.8) # Laisse le temps au site d'injecter les nouveaux éléments
            h_max = dr.execute_script("return document.body.scrollHeight")
            
        return list(catalog.values())
    finally: dr.quit()

# --- LOGIQUE PRINCIPALE ---

def run():
    tous_les_cours = get_data()
    if not tous_les_cours:
        logging.error("❌ Aucun cours n'a été détecté.")
        return

    # Tri chronologique
    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- AFFICHAGE DU TABLEAU DANS LES LOGS ---
    header = f"{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    sep = "-" * 95
    print(f"\n{sep}\n{header}\n{sep}")
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_suivis_actuels = []

    for c in tous_les_cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET": stats_jour[c['date']]["complets"] += 1
        
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi: cours_suivis_actuels.append(c)

    print(f"{sep}\n")
    for j, s in sorted(stats_jour.items()):
        logging.info(f"📊 {j} : {s['total']} cours détectés | {s['complets']} complets")

    # --- COMPARAISON MÉMOIRE ET ALERTES ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    for c in cours_suivis_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c)

    # Sauvegarde des cours complets pour le prochain passage
    complets_a_sauver = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(complets_a_sauver, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    try: run()
    except Exception as e: logging.error(f"Erreur critique : {e}")
