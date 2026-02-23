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
# Fichier d'historique des notifications pour éviter les doublons journaliers
NOTIFS_HISTORY_FILE = 'notifs_envoyees.json'

# Secrets
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- OUTILS DE GESTION DE LA MÉMOIRE ---

def load_and_clean_history():
    """
    Charge l'historique des notifications et supprime les entrées de plus de 7 jours.
    Gère le cas où le fichier n'existe pas encore (1ère exécution).
    """
    if not os.path.exists(NOTIFS_HISTORY_FILE):
        logging.info("📝 Premier lancement : création de l'historique des notifications.")
        return {}

    try:
        with open(NOTIFS_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (json.JSONDecodeError, Exception):
        return {}

    # Nettoyage : on ne garde que les 7 derniers jours
    date_limite = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    # On filtre le dictionnaire pour ne garder que les clés (dates) récentes
    history_nettoyee = {date: ids for date, ids in history.items() if date >= date_limite}
    
    return history_nettoyee

def save_history(history):
    """Sauvegarde le dictionnaire d'historique mis à jour."""
    try:
        with open(NOTIFS_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"❌ Erreur lors de la sauvegarde de l'historique : {e}")

# --- OUTILS DE FORMATAGE ---

def formater_date_relative(date_str):
    jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12: annee += 1
        date_objet = datetime(annee, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_semaine[date_objet.weekday()]
        if diff == 0: return f"Aujourd'hui ({nom_jour}) {date_str}"
        elif diff == 1: return f"Demain ({nom_jour}) {date_str}"
        else: return f"{nom_jour} {date_str}"
    except: return date_str

def send_final_notification(liste_alertes):
    if not liste_alertes: return
    nb = len(liste_alertes)
    titre = "🚨 PLACE LIBRE !" if nb == 1 else f"🚨 {nb} PLACES LIBÉRÉES !"
    corps = ""
    for a in liste_alertes:
        date_rel = formater_date_relative(a['date'])
        corps += (f"🏋️ *{a['nom']}*\n📅 {date_rel}\n⏰ {a['horaire']}\n🔥 {a['places']} place(s)!\n-------------------\n")
    
    msg_whatsapp = f"{titre}\n\n{corps}🔗 {URL_UCPA}"
    
    if GREEN_API_URL and WHATSAPP_CHAT_ID:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg_whatsapp}, timeout=10)
            logging.info("✅ Notification WhatsApp envoyée.")
        except Exception as e: logging.error(f"❌ Erreur GreenAPI: {e}")

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
        except Exception as e: logging.error(f"❌ Erreur Email: {e}")

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
            if int(jour_num) < maintenant.day and maintenant.day > 20: m_val = (m_val % 12) + 1
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
                    found_courses.append({"nom": nom_clean, "date": current_date, "horaire": horaire, "places": p_val, "statut": statut})
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Scan du planning UCPA...")
    try:
        headers = {"User-Agent": "Mozilla/5.0", "X-No-Cache": "true"}
        response = requests.get(URL_CIBLE, headers=headers, timeout=30)
        response.raise_for_status()
        tous_les_cours = extract_courses_from_markdown(response.text)
    except Exception as e:
        logging.error(f"❌ Erreur réseau : {e}")
        return

    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours trouvé.")
        return

    # 1. Charger l'historique (nettoyé des entrées de > 7 jours)
    history = load_and_clean_history()
    today_str = datetime.now().strftime("%Y-%m-%d")
    notifs_deja_faites_aujourdhui = history.get(today_str, [])

    # 2. Identifier les cours suivis
    cours_suivis_actuels = [c for c in tous_les_cours if not COURS_SURVEILLES or any(m in c['nom'].lower() for m in COURS_SURVEILLES)]

    # 3. Charger le statut précédent (pour détecter COMPLET -> LIBRE)
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    nouvelles_places_a_notifier = []
    
    for c in cours_suivis_actuels:
        id_unique = f"{c['nom']}|{c['date']}|{c['horaire']}"
        
        if c['statut'] == "LIBRE":
            # Condition A : Était complet au dernier scan ?
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_unique for a in anciens_complets)
            
            # Condition B : N'a pas encore été notifié AUJOURD'HUI ?
            pas_encore_notifie = id_unique not in notifs_deja_faites_aujourdhui

            if etait_complet and pas_encore_notifie:
                nouvelles_places_a_notifier.append(c)
                notifs_deja_faites_aujourdhui.append(id_unique)

    # 4. Envoi des notifications et mises à jour
    if nouvelles_places_a_notifier:
        logging.info(f"🚀 {len(nouvelles_places_a_notifier)} alerte(s) à envoyer !")
        send_final_notification(nouvelles_places_a_notifier)
        
        # Mise à jour de l'historique pour aujourd'hui
        history[today_str] = notifs_deja_faites_aujourdhui
        save_history(history)
    else:
        logging.info("ℹ️ Rien à notifier (déjà fait aujourd'hui ou pas de changement).")

    # Sauvegarde des cours complets pour le prochain scan
    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
