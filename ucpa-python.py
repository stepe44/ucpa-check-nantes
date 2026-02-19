import os
import json
import re
import requests
import logging
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
URL_CIBLE = f'https://r.jina.ai/{URL_UCPA}'
MEMO_FILE = 'memoire_ucpa.json'

# Secrets
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- OUTILS ---

def formater_date_relative(date_str):
    """Transforme '21/02' en 'Demain (Vendredi) 21/02'"""
    jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        # Gestion passage année suivante
        if mois == 1 and maintenant.month == 12:
            annee += 1
            
        date_objet = datetime(annee, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_semaine[date_objet.weekday()]
        
        if diff == 0:
            return f"Aujourd'hui ({nom_jour}) {date_str}"
        elif diff == 1:
            return f"Demain ({nom_jour}) {date_str}"
        else:
            return f"{nom_jour} {date_str}"
    except Exception:
        return date_str

def send_final_notification(liste_alertes):
    """Envoie un seul message groupé pour toutes les places libérées"""
    if not liste_alertes:
        return

    nb = len(liste_alertes)
    titre = "🚨 PLACE LIBRE !" if nb == 1 else f"🚨 {nb} PLACES LIBÉRÉES !"
    
    corps = ""
    for a in liste_alertes:
        date_rel = formater_date_relative(a['date'])
        corps += (f"🏋️ *{a['nom']}*\n"
                  f"📅 {date_rel}\n"
                  f"⏰ {a['horaire']}\n"
                  f"🔥 {a['places']} place(s)!\n"
                  f"-------------------\n")
    
    msg_whatsapp = f"{titre}\n\n{corps}🔗 {URL_UCPA}"
    
    # Envoi WhatsApp
    if GREEN_API_URL and WHATSAPP_CHAT_ID:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg_whatsapp}, timeout=10)
            logging.info("✅ Notification WhatsApp envoyée.")
        except Exception as e:
            logging.error(f"❌ Erreur GreenAPI: {e}")

    # Envoi Email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVERS:
        try:
            m = MIMEMultipart()
            m['Subject'] = titre
            m.attach(MIMEText(msg_whatsapp.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
            logging.info("✅ Notification Email envoyée.")
        except Exception as e:
            logging.error(f"❌ Erreur Email: {e}")

# --- MOTEUR D'EXTRACTION ---

def extract_courses_from_markdown(markdown_text):
    found_courses = []
    maintenant = datetime.now()
    current_date = None
    
    day_header_pattern = re.compile(r"^(\d{2})\s+(?:lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)", re.IGNORECASE)
    course_pattern = re.compile(r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})\s*#+\s*(.*)", re.IGNORECASE)

    for line in markdown_text.split('\n'):
        clean_line = line.strip().lstrip('* ').strip()
        
        day_match = day_header_pattern.match(clean_line)
        if day_match:
            jour_num = day_match.group(1)
            m_val = maintenant.month
            if int(jour_num) < maintenant.day and maintenant.day > 20:
                m_val = (m_val % 12) + 1
            current_date = f"{jour_num}/{str(m_val).zfill(2)}"
            continue

        if current_date and '#' in clean_line:
            course_match = course_pattern.search(clean_line)
            if course_match:
                horaire = course_match.group(1).strip()
                nom_brut = course_match.group(2).strip()
                
                p_match = re.search(r"(\d+)\s*places?\s*restantes?", nom_brut, re.IGNORECASE)
                p_val = int(p_match.group(1)) if p_match else 0
                
                nom_clean = re.sub(r"(\d+)\s*places?\s*restantes?|Complet|\[RÉSERVER\].*", "", nom_brut, flags=re.IGNORECASE).strip()
                statut = "LIBRE" if p_val > 0 else "COMPLET" if "Complet" in nom_brut else None
                
                if statut:
                    found_courses.append({
                        "nom": nom_clean, "date": current_date, "horaire": horaire,
                        "places": p_val, "statut": statut
                    })
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Scan du planning UCPA...")
    try:
        response = requests.get(URL_CIBLE, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        response.raise_for_status()
        tous_les_cours = extract_courses_from_markdown(response.text)
    except Exception as e:
        logging.error(f"❌ Erreur réseau : {e}")
        return

    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours trouvé.")
        return

    # Filtrage et Dashboard
    cours_suivis_actuels = []
    print(f"\n{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'NOM'}")
    print("-" * 80)

    for c in tous_les_cours:
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {'[X] ' if est_suivi else '    '}{c['nom']}")
        if est_suivi:
            cours_suivis_actuels.append(c)

    # Gestion Mémoire et Alertes
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    nouvelles_places = []
    for c in cours_suivis_actuels:
        if c['statut'] == "LIBRE":
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            # Une alerte si le cours était marqué COMPLET au dernier scan
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                nouvelles_places.append(c)

    if nouvelles_places:
        logging.info(f"🚀 {len(nouvelles_places)} nouvelle(s) place(s) détectée(s) !")
        send_final_notification(nouvelles_places)

    # Sauvegarde des cours complets pour le prochain scan
    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
