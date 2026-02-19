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

# L'URL Jina se charge de l'interprétation JS dynamique du tableau pour nous
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

# --- FONCTIONS UTILITAIRES ---

def send_alerts(course):
    """Notification WhatsApp et Email"""
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

# --- MOTEUR D'EXTRACTION ---

def parse_markdown_content(text):
    """Analyse le Markdown rendu par Jina pour extraire 100% des cours"""
    found_courses = []
    maintenant = datetime.now()
    
    # Séparation par blocs de jours (ex: "20 ven.")
    # On cherche un chiffre suivi d'un jour de la semaine en minuscule
    sections = re.split(r"(\d{2}\s+(?:lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.))", text, flags=re.IGNORECASE)
    
    for i in range(1, len(sections), 2):
        jour_brut = sections[i].strip().split(' ')[0]
        bloc_contenu = sections[i+1]
        
        # Calcul du mois (gestion fin de mois)
        m_val = maintenant.month
        if int(jour_brut) < maintenant.day and maintenant.day > 20:
            m_val = (m_val % 12) + 1
        date_cle = f"{jour_brut}/{str(m_val).zfill(2)}"

        # Regex adaptée au Markdown de Jina Reader
        # Format attendu : 19h15 - 20h00 #### Nom du cours (places ou Complet)
        pattern = r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\s*####\s*(.*?)\s*(?:(\d+)\s*places? restantes|Complet)"
        
        for m in re.finditer(pattern, bloc_contenu):
            horaire = m.group(1).strip()
            nom = m.group(2).strip()
            places = m.group(3)
            
            found_courses.append({
                "nom": nom, "date": date_cle, "horaire": horaire,
                "places": int(places) if places else 0,
                "statut": "LIBRE" if places else "COMPLET"
            })
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run_scan():
    logging.info(f"🌐 Chargement du tableau (Rendu JS via Jina)...")
    try:
        # On force un User-Agent pour éviter d'être bloqué par Jina
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(URL_CIBLE, headers=headers, timeout=30)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        logging.error(f"❌ Erreur lors de la récupération via Jina : {e}")
        return

    tous_les_cours = parse_markdown_content(content)
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours extrait. Vérifiez l'URL Jina.")
        return

    # Tri chronologique pour le log
    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- AFFICHAGE DU TABLEAU DE LOG ---
    header = f"{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    sep = "-" * 100
    print(f"\n{sep}\n{header}\n{sep}")
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_a_surveiller = []

    for c in tous_les_cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET":
            stats_jour[c['date']]["complets"] += 1
            
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {'[X]' if est_suivi else '[ ]':<5} | {c['nom']}")
        if est_suivi:
            cours_a_surveiller.append(c)

    print(f"{sep}\n")
    
    # --- LOG DES STATS PAR JOUR ---
    for j, s in sorted(stats_jour.items()):
        logging.info(f"📊 {j} : {s['total']} cours détectés | {s['complets']} complets")
    logging.info("========================================")

    # --- COMPARAISON MÉMOIRE ET ALERTES ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    for c in cours_a_surveiller:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            # On alerte si le cours était dans la liste des "COMPLET" au scan précédent
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 PLACE LIBÉRÉE : {c['nom']} le {c['date']} !")
                send_alerts(c)

    # Sauvegarde des cours complets pour le prochain passage
    nouveaux_complets = [c for c in cours_a_surveiller if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run_scan()
