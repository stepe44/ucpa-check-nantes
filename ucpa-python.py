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

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

# --- OUTILS ---

def formater_date_relative(date_str):
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    try:
        j, m = map(int, date_str.split('/'))
        date_obj = datetime(datetime.now().year, m, j)
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
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
        except: pass

# --- NOUVEAU MOTEUR DE CAPTURE PAR COLONNE ---

def parse_day_text(date_str, text):
    """Analyse le texte spécifique à une seule journée"""
    results = []
    # On découpe par bloc d'heure
    blocs = re.split(r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})", text)
    for i in range(1, len(blocs), 2):
        horaire = blocs[i].strip()
        contenu = blocs[i+1].strip()
        lignes = [l.strip() for l in contenu.split('\n') if l.strip()]
        if not lignes: continue
        
        nom = lignes[0]
        p_match = re.search(r"(\d+)\s*places? restantes", contenu)
        est_complet = "Complet" in contenu
        
        p_val = int(p_match.group(1)) if p_match else 0
        statut = "LIBRE" if p_val > 0 else "COMPLET" if est_complet else None
        
        if statut:
            results.append({
                "nom": nom, "date": date_str, "horaire": horaire,
                "places": p_val, "statut": statut
            })
    return results

def get_data():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("window-size=1920,3000") # Très haut pour tout voir
    dr = webdriver.Chrome(options=opts)
    
    catalog = {}
    try:
        logging.info("🌐 Navigation vers l'UCPA...")
        dr.get(URL_CIBLE)
        time.sleep(15) # Attente rendu JS
        
        # 1. Identifier les colonnes de jours par les headers (LUN., MAR., etc.)
        # On cherche les éléments qui contiennent la date (ex: "20 VEN.")
        headers = dr.find_elements(By.XPATH, "//div[contains(text(), 'LUN.') or contains(text(), 'MAR.') or contains(text(), 'MER.') or contains(text(), 'JEU.') or contains(text(), 'VEN.') or contains(text(), 'SAM.') or contains(text(), 'DIM.')]")
        
        for h in headers:
            try:
                txt_h = h.text
                match_date = re.search(r"(\d{2})", txt_h)
                if not match_date: continue
                
                jour_num = match_date.group(1)
                m_val = datetime.now().month
                if int(jour_num) < datetime.now().day and datetime.now().day > 20: m_val = (m_val % 12) + 1
                date_cle = f"{jour_num}/{str(m_val).zfill(2)}"
                
                # On remonte au parent qui contient toute la colonne du jour
                # Souvent c'est un div qui contient le header et tous les cours dessous
                colonne = h.find_element(By.XPATH, "./ancestor::div[contains(@class, 'column') or contains(@class, 'day')] | ./parent::div")
                
                # On extrait le texte UNIQUEMENT de cette colonne
                txt_colonne = colonne.text
                logging.info(f"🔎 Analyse de la colonne du {date_cle}...")
                
                for c in parse_day_text(date_cle, txt_colonne):
                    catalog[f"{c['date']}|{c['horaire']}|{c['nom']}"] = c
            except: continue
            
        return list(catalog.values())
    finally: dr.quit()

# --- LOGIQUE DE SCAN ---

def run():
    cours = get_data()
    if not cours:
        logging.warning("⚠️ Aucun cours trouvé. Tentative avec méthode de secours...")
        # Ici on pourrait ajouter un fallback si les colonnes ne sont pas trouvées
        return

    cours.sort(key=lambda x: (x['date'], x['horaire']))

    print(f"\n{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}")
    print("-" * 100)
    
    stats = defaultdict(lambda: {"total": 0, "complet": 0})
    a_surveiller = []

    for c in cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats[c['date']]["total"] += 1
        if c['statut'] == "COMPLET": stats[c['date']]["complet"] += 1
        
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi: a_surveiller.append(c)

    print("-" * 100)
    for d, s in sorted(stats.items()):
        logging.info(f"📊 {d} : {s['total']} cours détectés | {s['complet']} complets")

    # Comparaison mémoire
    anciens = []
    if os.path.exists(MEMO_FILE):
        try: anciens = json.load(open(MEMO_FILE, 'r', encoding='utf-8'))
        except: pass

    for c in a_surveiller:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens):
                logging.info(f"🔥 PLACE LIBÉRÉE : {c['nom']} !")
                send_alerts(c)

    # Sauvegarde des complets
    nouveaux_complets = [c for c in a_surveiller if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
