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

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'

# Récupération des filtres
raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# Secrets pour notifications
# GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

# --- OUTILS ---

def formater_date_relative(date_str):
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    try:
        j, m = map(int, date_str.split('/'))
        date_obj = datetime(maintenant.year, m, j)
        diff = (date_obj.date() - maintenant.date()).days
        nom = jours[date_obj.weekday()]
        return f"Aujourd'hui ({nom}) {date_str}" if diff == 0 else f"Demain ({nom}) {date_str}" if diff == 1 else f"{nom} {date_str}"
    except: return date_str

def send_alerts(course):
    """Envoi des notifications WhatsApp et Email"""
    date_txt = formater_date_relative(course['date'])
    msg = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course['nom']}*\n📅 {date_txt}\n⏰ {course['horaire_full']}\n🔥 {course['places']} places!\n🔗 {URL_CIBLE}"
    
    # WhatsApp
    if GREEN_API_URL:
        try: requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg}, timeout=10)
        except Exception as e: logging.error(f"Erreur WhatsApp: {e}")
    
    # Email
    if EMAIL_SENDER and EMAIL_PASSWORD:
        try:
            m = MIMEMultipart()
            m['Subject'] = f"🚨 Place UCPA : {course['nom']}"
            m.attach(MIMEText(msg.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
        except Exception as e: logging.error(f"Erreur Email: {e}")

# --- MOTEUR DE SCRAPING CUMULATIF ---

def extract_from_text(text):
    """Analyse le texte avec une regex permissive pour ne rater aucun bloc"""
    results = []
    maintenant = datetime.now()
    
    # Découpage par jour (ex: 20 VEN.)
    sections = re.split(r"(\d{2}\s+(?:LUN\.|MAR\.|MER\.|JEU\.|VEN\.|SAM\.|DIM\.))", text)
    
    for i in range(1, len(sections), 2):
        date_brute = sections[i].strip().split(' ')[0]
        bloc_jour = sections[i+1]
        
        m_val = maintenant.month
        if int(date_brute) < maintenant.day and maintenant.day > 20: m_val = (m_val % 12) + 1
        date_cle = f"{date_brute}/{str(m_val).zfill(2)}"

        # Regex adaptée à l'image : Heure -> Nom -> (Places ou Complet) -> (Optionnel Réserver)
        pattern = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\n(.*?)\n(?:(\d+)\s*places? restantes|Complet)"
        
        for match in re.finditer(pattern, bloc_jour, re.MULTILINE):
            h_full = match.group(1).strip()
            nom = match.group(2).strip().split('\n')[0] # Sécurité si texte parasite
            p = match.group(3)
            
            results.append({
                "nom": nom, "date": date_cle, "horaire_full": h_full,
                "places": int(p) if p else 0,
                "statut": "LIBRE" if p else "COMPLET"
            })
    return results

def get_data():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("window-size=1920,1080")
    dr = webdriver.Chrome(options=opts)
    
    catalog = {} # Utilisation d'un dict pour fusionner les captures sans doublons
    try:
        logging.info("🚀 Démarrage du scan cumulatif...")
        dr.get(URL_CIBLE)
        time.sleep(10) # Attente JS
        
        # Scroll ultra-fin (300px) pour forcer le chargement de chaque carte
        h_tot = dr.execute_script("return document.body.scrollHeight")
        pos = 0
        while pos < h_tot:
            # On capture le texte à chaque étape
            txt = dr.find_element(By.TAG_NAME, "body").text
            for c in extract_from_text(txt):
                # ID unique : Date + Heure + Nom
                catalog[f"{c['date']}|{c['horaire_full']}|{c['nom']}"] = c
            
            pos += 350 # Pas de scroll court
            dr.execute_script(f"window.scrollTo(0, {pos});")
            time.sleep(1.2) # Laisse le temps au DOM de s'actualiser
            h_tot = dr.execute_script("return document.body.scrollHeight")
            
        return list(catalog.values())
    finally: dr.quit()

# --- LOGIQUE PRINCIPALE ---

def run():
    cours_detectes = get_data()
    if not cours_detectes:
        logging.error("❌ Aucun cours trouvé. Vérifiez la connexion ou le sélecteur.")
        return

    cours_detectes.sort(key=lambda x: (x['date'], x['horaire_full']))

    # Affichage du tableau de log
    print(f"\n{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}")
    print("-" * 95)
    
    stats = defaultdict(lambda: {"vu": 0, "full": 0})
    a_surveiller = []

    for c in cours_detectes:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats[c['date']]["vu"] += 1
        if c['statut'] == "COMPLET": stats[c['date']]["full"] += 1
        
        print(f"{c['date']:<6} | {c['horaire_full']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi: a_surveiller.append(c)

    print("-" * 95)
    for d, s in sorted(stats.items()):
        logging.info(f"📊 {d} : {s['vu']} cours détectés | {s['full']} complets")

    # Comparaison mémoire pour alertes
    anciens = []
    if os.path.exists(MEMO_FILE):
        try: anciens = json.load(open(MEMO_FILE, 'r', encoding='utf-8'))
        except: pass

    # Alertes si : est LIBRE maintenant ET était COMPLET avant (ou absent)
    # Note : On ne stocke que les COMPLET dans le JSON
    for c in a_surveiller:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire_full']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire_full']}" == id_c for a in anciens):
                logging.info(f"🔥 PLACE LIBÉRÉE : {c['nom']} !")
                send_alerts(c)

    # Mise à jour mémoire (on ne garde que les complets suivis)
    nouveaux_complets = [c for c in a_surveiller if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
