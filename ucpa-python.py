import os
import json
import re
import requests
import logging
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
URL_CIBLE = f'https://r.jina.ai/{URL_UCPA}'
MEMO_FILE = 'memoire_ucpa.json'

# --- RÉCUPÉRATION DES SECRETS ---
# GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- NOTIFICATIONS ---

def send_alerts(course):
    msg = (f"🚨 *PLACE LIBRE !*\n\n"
           f"🏋️ *{course['nom']}*\n"
           f"📅 {course['date']}\n"
           f"⏰ {course['horaire']}\n"
           f"🔥 {course['places']} places!\n"
           f"🔗 {URL_UCPA}")
    
    if GREEN_API_URL:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg}, timeout=10)
        except Exception: pass
        
    if EMAIL_SENDER and EMAIL_PASSWORD:
        try:
            m = MIMEMultipart()
            m['Subject'] = f"🚨 Place UCPA : {course['nom']}"
            m.attach(MIMEText(msg.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
        except Exception: pass

# --- MOTEUR D'EXTRACTION CORRIGÉ ---

def extract_courses_from_markdown(markdown_text):
    """Analyse le Markdown avec une Regex flexible sur le singulier/pluriel"""
    found_courses = []
    maintenant = datetime.now()
    current_date = None
    
    # Détection du jour (ex: "20 ven.")
    day_header_pattern = re.compile(r"^(\d{2})\s+(?:lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)", re.IGNORECASE)
    
    # Regex de cours : gère "place restante" (singulier) et "places restantes" (pluriel)
    # On capture l'horaire, puis tout le reste de la ligne
    course_pattern = re.compile(r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\s*#+\s*(.*)", re.IGNORECASE)

    for line in markdown_text.split('\n'):
        # Nettoyage de la ligne (retrait des puces markdown et espaces)
        clean_line = line.strip().lstrip('* ').strip()
        
        # 1. Changement de jour
        day_match = day_header_pattern.match(clean_line)
        if day_match:
            jour_num = day_match.group(1)
            m_val = maintenant.month
            if int(jour_num) < maintenant.day and maintenant.day > 20:
                m_val = (m_val % 12) + 1
            current_date = f"{jour_num}/{str(m_val).zfill(2)}"
            continue

        # 2. Extraction du cours
        if current_date and '#' in clean_line:
            course_match = course_pattern.search(clean_line)
            if course_match:
                horaire = course_match.group(1).strip()
                nom_brut = course_match.group(2).strip()
                
                # Extraction des places avec gestion optionnelle du 's'
                p_match = re.search(r"(\d+)\s*places?\s*restantes?", nom_brut, re.IGNORECASE)
                p_val = int(p_match.group(1)) if p_match else 0
                
                # Nettoyage du nom pour enlever les résidus de statut et liens
                nom_clean = re.sub(r"(\d+)\s*places?\s*restantes?|Complet|\[RÉSERVER\].*", "", nom_brut, flags=re.IGNORECASE).strip()
                
                # Détermination du statut
                statut = "LIBRE" if p_val > 0 else "COMPLET" if "Complet" in nom_brut else None
                
                if statut:
                    found_courses.append({
                        "nom": nom_clean, "date": current_date, "horaire": horaire,
                        "places": p_val, "statut": statut
                    })
                    
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info(f"🌐 Récupération via Jina Reader...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(URL_CIBLE, headers=headers, timeout=30)
        response.raise_for_status()
        raw_markdown = response.text
    except Exception as e:
        logging.error(f"❌ Erreur réseau : {e}")
        return

    # DEBUG ARTIFACT
    print("\n" + "="*30 + " DEBUG SOURCE START " + "="*30)
    # On n'affiche qu'un extrait pour le log si trop long
    print(raw_markdown[:10000]) 
    print("="*31 + " DEBUG SOURCE END " + "="*31 + "\n")

    tous_les_cours = extract_courses_from_markdown(raw_markdown)
    
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours extrait.")
        return

    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # TABLEAU DE LOG
    header = f"{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    sep = "-" * 105
    print(f"\n{header}\n{sep}")
    
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

    # MÉMOIRE ET ALERTES
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f: anciens_complets = json.load(f)
        except: pass

    for c in cours_suivis_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c)

    # Sauvegarde
    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
