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

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
# Jina Reader gère l'interprétation JS dynamique pour nous
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

# --- FONCTIONS DE NOTIFICATION ---

def send_alerts(course):
    msg = f"🚨 *PLACE LIBRE !*\n\n🏋️ *{course['nom']}*\n📅 {course['date']}\n⏰ {course['horaire']}\n🔥 {course['places']} places!\n🔗 {URL_UCPA}"
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

# --- NOUVEAU MOTEUR D'EXTRACTION LIGNE PAR LIGNE ---

def parse_jina_markdown(text):
    """Analyse le Markdown ligne par ligne pour ne rater aucun cours simultané"""
    found_courses = []
    maintenant = datetime.now()
    
    # Séparation par blocs de jours (ex: "20 ven.")
    sections = re.split(r"(\d{2}\s+(?:lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.))", text, flags=re.IGNORECASE)
    
    for i in range(1, len(sections), 2):
        jour_num = sections[i].strip().split(' ')[0]
        bloc_contenu = sections[i+1]
        
        # Calcul du mois
        m_val = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            m_val = (m_val % 12) + 1
        date_cle = f"{jour_num}/{str(m_val).zfill(2)}"

        # On analyse chaque ligne du bloc séparément
        lines = bloc_contenu.split('\n')
        for line in lines:
            if '####' not in line: continue # On ne traite que les lignes de cours
            
            # Extraction : Horaire | Nom | Places/Complet
            # Format Jina : * 19h15 - 20h00 #### Nom du cours 14 places restantes...
            match_h = re.search(r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})", line)
            if not match_h: continue
            
            horaire = match_h.group(1).strip()
            # Le nom est entre '####' et le statut
            nom_part = line.split('####')[1].strip()
            
            # Extraction des places
            p_match = re.search(r"(\d+)\s*places? restantes", nom_part)
            p_val = int(p_match.group(1)) if p_match else 0
            
            # Nettoyage du nom : on enlève les infos de places/complet et les liens
            nom_clean = re.sub(r"(\d+)\s*places? restantes|Complet|\[RÉSERVER\].*", "", nom_part).strip()
            
            statut = "LIBRE" if p_val > 0 else "COMPLET" if "Complet" in nom_part else "INCONNU"
            
            if statut != "INCONNU":
                found_courses.append({
                    "nom": nom_clean, "date": date_cle, "horaire": horaire,
                    "places": p_val, "statut": statut
                })
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run_scan():
    logging.info("🌐 Récupération du planning via Jina Reader (JS Rendered)...")
    try:
        # User-Agent pour simuler un navigateur et éviter le blocage
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(URL_CIBLE, headers=headers, timeout=30)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        logging.error(f"❌ Erreur de récupération : {e}")
        return

    tous_les_cours = parse_jina_markdown(content)
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours trouvé.")
        return

    # Tri pour le log
    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- TABLEAU DE LOG ---
    header = f"{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    sep = "-" * 105
    print(f"\n{sep}\n{header}\n{sep}")
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_a_surveiller = []

    for c in tous_les_cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET": stats_jour[c['date']]["complets"] += 1
        
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi: cours_a_surveiller.append(c)

    print(f"{sep}\n")
    for j, s in sorted(stats_jour.items()):
        logging.info(f"📊 {j} : {s['total']} cours détectés | {s['complets']} complets")

    # --- ALERTES ET MÉMOIRE ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f: anciens_complets = json.load(f)
        except: pass

    for c in cours_a_surveiller:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c)

    # Mise à jour mémoire
    complets_suivis = [c for c in cours_a_surveiller if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(complets_suivis, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run_scan()
