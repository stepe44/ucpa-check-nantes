import os
import re
import json
import requests
import logging
import smtplib
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
MEMO_FILE = 'memoire_ucpa.json'
NOTIFS_HISTORY_FILE = 'notifs_envoyees.json'

# Variables d'environnement
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
    "rpm": "🚴",
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
    "hyrox": "🏃",
    "stretching": "🧘"
}

def get_course_emoji(nom_cours):
    nom_lower = nom_cours.lower()
    for keyword, emoji in EMOJI_MAP.items():
        if keyword in nom_lower:
            return emoji
    return "🏋️"

# --- GESTION HISTORIQUE & FORMATAGE ---

def load_and_clean_history():
    if not os.path.exists(NOTIFS_HISTORY_FILE):
        return {}
    try:
        with open(NOTIFS_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
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
    jours_semaine_court = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12:
            annee += 1
        date_objet = datetime(annee, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_semaine_court[date_objet.weekday()]
        
        if diff == 0:
            return f"Auj. ({nom_jour})"
        elif diff == 1:
            return f"Demain ({nom_jour})"
        else:
            return f"{nom_jour} {date_str}"
    except Exception:
        return date_str

def est_semaine_prochaine(date_str):
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12:
            annee += 1
        date_objet = datetime(annee, mois, jour)
        debut_semaine_prochaine = maintenant + timedelta(days=(7 - maintenant.weekday()))
        return date_objet.date() >= debut_semaine_prochaine.date()
    except Exception:
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
        except Exception:
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
    
    msg_final = corps
    
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
            m.attach(MIMEText(msg_final.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
            logging.info("✅ Notification Email envoyée")
        except Exception as e: 
            logging.error(f"❌ Erreur Email: {e}")

# --- EXTRACTION DIRECTE HTML ---

def fetch_and_extract_courses():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(URL_UCPA, headers=headers, timeout=15)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    texte = soup.get_text("\n")
    lignes = [l.strip() for l in texte.split("\n") if l.strip()]
    
    found_courses = []
    
    # Repérage du mois affiché dans l'intervalle de semaine (ex: "Semaine du 07 septembre au 13 septembre08/09 - 13/09")
    mois_courant = datetime.now().strftime("%m")
    for l in lignes:
        match_intervalle = re.search(r"\d{2}/(\d{2})\s*-\s*\d{2}/(\d{2})", l)
        if match_intervalle:
            mois_courant = match_intervalle.group(1)
            break

    regex_jour = re.compile(r"^(\d{2})\s+(lun|mar|mer|jeu|ven|sam|dim)\.?", re.IGNORECASE)
    regex_horaire = re.compile(r"^\d{2}h\d{2}\s*-\s*\d{2}h\d{2}$")

    date_courante = f"{datetime.now().strftime('%d')}/{mois_courant}"
    
    i = 0
    n = len(lignes)
    while i < n:
        ligne = lignes[i]
        
        # 1. Détection d'en-tête de jour (ex: "08 mar.")
        m_jour = regex_jour.match(ligne)
        if m_jour:
            jour_num = m_jour.group(1)
            date_courante = f"{jour_num}/{mois_courant}"
            i += 1
            continue
            
        # 2. Détection d'un bloc de cours via l'horaire
        if regex_horaire.match(ligne):
            horaire = ligne
            nom_cours = "Cours Inconnu"
            statut = "COMPLET"
            places = 0
            
            # On lit les 3 lignes suivantes pour isoler le nom et le stock
            j = i + 1
            while j < min(i + 5, n):
                val = lignes[j]
                # Si on tombe sur un nouvel horaire ou un jour, fin du bloc
                if regex_horaire.match(val) or regex_jour.match(val):
                    break
                if val.upper() in ["RÉSERVER", "RESERVER"]:
                    j += 1
                    continue
                if "places restantes" in val.lower() or "place restante" in val.lower():
                    chiffres = re.findall(r"\d+", val)
                    places = int(chiffres[0]) if chiffres else 1
                    statut = "LIBRE"
                elif val.lower() == "complet":
                    statut = "COMPLET"
                    places = 0
                elif nom_cours == "Cours Inconnu":
                    nom_cours = val
                j += 1
                
            found_courses.append({
                "nom": nom_cours,
                "date": date_courante,
                "horaire": horaire,
                "places": places,
                "statut": statut
            })
            i = j
            continue
            
        i += 1

    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Analyse du planning sur la page UCPA...")
    try:
        tous_les_cours = fetch_and_extract_courses()
    except Exception as e:
        logging.error(f"❌ Erreur lors de l'extraction : {e}")
        return

    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours extrait de la page.")
        return

    logging.info(f"✅ {len(tous_les_cours)} cours récupérés sur le planning.")

    history = load_and_clean_history()
    maintenant = datetime.now()
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
        except Exception:
            pass

    nouvelles_places_a_notifier = []
    for c in cours_suivis_actuels:
        id_unique = f"{c['nom']}|{c['date']}|{c['horaire']}"
        
        # Filtre temporel : ignorer les cours commençant dans moins de 60 min
        try:
            jour, mois = map(int, c['date'].split('/'))
            heure, minute = map(int, c['horaire'].split(' - ')[0].replace('h', ':').split(':'))
            annee = maintenant.year
            if mois == 1 and maintenant.month == 12:
                annee += 1
            date_objet_cours = datetime(annee, mois, jour, heure, minute)
            if date_objet_cours < (maintenant + timedelta(minutes=60)):
                continue
        except Exception:
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

    # Sauvegarde des cours complets pour comparaison au tour suivant
    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    try:
        with open(MEMO_FILE, 'w', encoding='utf-8') as f:
            json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"❌ Erreur lors de l'écriture du mémo : {e}")

if __name__ == "__main__":
    run()
