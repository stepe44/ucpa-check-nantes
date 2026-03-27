import os
import json
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
API_BASE_URL = 'https://www.ucpa.com/sport-station/api/areas-offers/weekly/alpha_nan'

MEMO_FILE = 'memoire_ucpa.json'
NOTIFS_HISTORY_FILE = 'notifs_envoyees.json'

# Secrets (Variables d'environnement)
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- DICTIONNAIRE D'EMOJIS ---
EMOJI_MAP = {
    "biking": "🚴",
    "yoga": "🧘",
    "pilates": "🤸",
    "zumba": "💃",
    "danse": "💃",
    "boxe": "🥊",
    "caf": "💪",
    "cuisses": "💪",
    "cross": "🏋️",
    "hiit": "🔥",
    "body": "⚡",
}

def get_course_emoji(nom_cours):
    """Retourne l'emoji correspondant au nom du cours."""
    nom_lower = nom_cours.lower()
    for keyword, emoji in EMOJI_MAP.items():
        if keyword in nom_lower:
            return emoji
    return "🏋️"

# --- OUTILS DE GESTION DE LA MÉMOIRE ---

def load_and_clean_history():
    if not os.path.exists(NOTIFS_HISTORY_FILE):
        return {}
    try:
        with open(NOTIFS_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except:
        return {}
    date_limite = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    return {date: ids for date, ids in history.items() if date >= date_limite}

def save_history(history):
    try:
        with open(NOTIFS_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"❌ Erreur sauvegarde de l'historique : {e}")

def formater_date_relative(date_str):
    """Transforme 'DD/MM' en 'Auj. (Jeu)', 'Demain (Ven)' ou 'Jeu 27/03'."""
    jours_semaine_court = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12: annee += 1
        date_objet = datetime(annee, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        
        nom_jour = jours_semaine_court[date_objet.weekday()]
        
        if diff == 0:
            return f"Auj. ({nom_jour})"
        elif diff == 1:
            return f"Demain ({nom_jour})"
        else:
            return f"{nom_jour} {date_str}"
    except:
        return date_str

def est_semaine_prochaine(date_str):
    """Vérifie si la date appartient à la semaine prochaine."""
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12: annee += 1
        date_objet = datetime(annee, mois, jour)
        debut_semaine_prochaine = maintenant + timedelta(days=(7 - maintenant.weekday()))
        return date_objet.date() >= debut_semaine_prochaine.date()
    except:
        return False

# --- NOTIFICATIONS ---

def send_final_notification(liste_alertes):
    if not liste_alertes:
        return
    
    nb = len(liste_alertes)
    titre = "🚨 *COURS LIBRE !*" if nb == 1 else f"🚨 *{nb} COURS LIBÉRÉS !*"
    separateur = "━━━━━━━━━━━━━━━"
    
    def tri_chronologique(cours):
        try:
            jour, mois = map(int, cours['date'].split('/'))
            heure, minute = map(int, cours['horaire'].split(' - ')[0].replace('h', ':').split(':'))
            return (mois, jour, heure, minute)
        except:
            return (99, 99, 99, 99)

    liste_triee = sorted(liste_alertes, key=tri_chronologique)
    
    cette_semaine = [a for a in liste_triee if not est_semaine_prochaine(a['date'])]
    semaine_prochaine = [a for a in liste_triee if est_semaine_prochaine(a['date'])]
    
    corps = f"{titre}\n\n"
    
    def formater_bloc(liste, label):
        nonlocal corps
        if not liste:
            return
        corps += f"📅 *{label.upper()}*\n{separateur}\n"
        for a in liste:
            date_fmt = formater_date_relative(a['date'])
            prefixe_urgence = "⚡ " if "Auj." in date_fmt else ""
            emoji = get_course_emoji(a['nom'])
            
            corps += f"{prefixe_urgence}{emoji} *{a['nom'].upper()}*\n"
            corps += f"🔹 {date_fmt} à *{a['horaire']}* ({a['places']} pl.)\n\n"
        

    formater_bloc(cette_semaine, "Cette semaine")
    formater_bloc(semaine_prochaine, "Semaine prochaine")
    
    msg_final = f"{corps}"
    
    if GREEN_API_URL and WHATSAPP_CHAT_ID:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg_final}, timeout=10)
            logging.info("✅ Notification WhatsApp envoyée")
        except Exception as e: 
            logging.error(f"❌ Erreur GreenAPI: {e}")

    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVERS:
        try:
            m = MIMEMultipart()
            m['Subject'] = titre.replace('*', '')
            m['From'] = EMAIL_SENDER
            m['To'] = ", ".join(EMAIL_RECEIVERS)
            texte_email = msg_final.replace('*', '')
            m.attach(MIMEText(texte_email, 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
            logging.info("✅ Notification Email envoyée")
        except Exception as e: 
            logging.error(f"❌ Erreur Email: {e}")

# --- MOTEUR D'EXTRACTION ---

def fetch_api_week(date_cible):
    params = {
        'reservationPeriod': '1',
        'espace': 'area_1680850484_13e5a1d0-d511-11ed-93bb-77fd2e78b8a9',
        'time': date_cible,
        '__amp_source_origin': 'https://www.ucpa.com'
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(API_BASE_URL, params=params, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()

def extract_courses_from_api(json_data):
    found_courses = []
    try:
        planner = json_data.get('planner', {})
        columns = planner.get('columns', [])
        for column in columns:
            items = column.get('items', [])
            for item in items:
                nom = item.get('type', 'Cours Inconnu')
                heure_debut = item.get('startTime', '??h??')
                heure_fin = item.get('endTime', '??h??')
                horaire = f"{heure_debut} - {heure_fin}"
                start_date_raw = item.get('startDate', '')
                if start_date_raw and '/' in start_date_raw:
                    parts = start_date_raw.split('/')
                    date_fr = f"{parts[0]}/{parts[1]}"
                else:
                    date_fr = "??/??"
                places_restantes = int(item.get('stock', 0))
                statut = "LIBRE" if places_restantes > 0 else "COMPLET"
                found_courses.append({
                    "nom": nom, "date": date_fr, "horaire": horaire,
                    "places": places_restantes, "statut": statut
                })
    except Exception as e:
        logging.error(f"⚠️ Erreur d'extraction depuis le JSON : {e}")
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Scan de l'API UCPA...")
    maintenant = datetime.now()
    date_s1 = maintenant.strftime("%d-%m-%Y")
    date_s2 = (maintenant + timedelta(days=7)).strftime("%d-%m-%Y")

    tous_les_cours = []
    try:
        json_s1 = fetch_api_week(date_s1)
        json_s2 = fetch_api_week(date_s2)
        tous_les_cours.extend(extract_courses_from_api(json_s1))
        tous_les_cours.extend(extract_courses_from_api(json_s2))
    except Exception as e:
        logging.error(f"❌ Erreur réseau ou API : {e}")
        return

    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours extrait.")
        return

    history = load_and_clean_history()
    today_str = maintenant.strftime("%Y-%m-%d")
    notifs_deja_faites_aujourdhui = history.get(today_str, [])

    cours_suivis_actuels = [
        c for c in tous_les_cours 
        if not COURS_SURVEILLES or any(m in c['nom'].lower() for m in COURS_SURVEILLES)
    ]

    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: 
            pass

    nouvelles_places_a_notifier = []
    for c in cours_suivis_actuels:
        id_unique = f"{c['nom']}|{c['date']}|{c['horaire']}"
        
        # --- FILTRE TEMPOREL (30 min) ---
        try:
            jour, mois = map(int, c['date'].split('/'))
            heure, minute = map(int, c['horaire'].split(' - ')[0].replace('h', ':').split(':'))
            annee = maintenant.year
            if mois == 1 and maintenant.month == 12: annee += 1
            date_objet_cours = datetime(annee, mois, jour, heure, minute)
            
            # Si le cours est aujourd'hui et commence dans moins de 30 min (ou déjà commencé)
            if date_objet_cours < (maintenant + timedelta(minutes=30)):
                continue
        except:
            pass
        
        if c['statut'] == "LIBRE":
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_unique for a in anciens_complets)
            pas_encore_notifie = id_unique not in notifs_deja_faites_aujourdhui
            
            if etait_complet and pas_encore_notifie:
                nouvelles_places_a_notifier.append(c)
                notifs_deja_faites_aujourdhui.append(id_unique)

    if nouvelles_places_a_notifier:
        logging.info(f"🚀 {len(nouvelles_places_a_notifier)} alertes à envoyer.")
        send_final_notification(nouvelles_places_a_notifier)
        history[today_str] = notifs_deja_faites_aujourdhui
        save_history(history)
    else:
        logging.info("ℹ️ Pas de nouvelles places à notifier.")

    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    try:
        with open(MEMO_FILE, 'w', encoding='utf-8') as f:
            json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"❌ Erreur lors de l'écriture du mémo : {e}")

if __name__ == "__main__":
    run()
