import os
import json
import requests
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
API_BASE_URL = 'https://www.ucpa.com/sport-station/api/areas-offers/weekly/alpha_nan'

MEMO_FILE = 'memoire_ucpa.json'
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

# --- FORMATAGE LISIBILITÉ ---

def formater_date_relative(date_str):
    jours_courts = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    maintenant = datetime.now()
    try:
        jour, mois = map(int, date_str.split('/'))
        annee = maintenant.year
        if mois == 1 and maintenant.month == 12: annee += 1
        date_objet = datetime(annee, mois, jour)
        diff = (date_objet.date() - maintenant.date()).days
        nom_jour = jours_courts[date_objet.weekday()]
        
        if diff == 0: return f"Auj. ({nom_jour})"
        elif diff == 1: return f"Dem. ({nom_jour})"
        else: return f"{nom_jour} {date_str}"
    except: return date_str

def send_final_notification(liste_alertes):
    if not liste_alertes: return
    
    # Tri et séparation par semaine
    maintenant = datetime.now()
    # Fin de semaine = Dimanche soir
    fin_semaine = maintenant + timedelta(days=(6 - maintenant.weekday()))
    
    semaine_actuelle = []
    semaine_prochaine = []
    
    for a in liste_alertes:
        try:
            j, m = map(int, a['date'].split('/'))
            d_obj = datetime(maintenant.year, m, j)
            if d_obj.date() <= fin_semaine.date():
                semaine_actuelle.append(a)
            else:
                semaine_prochaine.append(a)
        except:
            semaine_actuelle.append(a)

    nb = len(liste_alertes)
    titre = "🚨 *PLACE LIBRE !*" if nb == 1 else f"🚨 *{nb} PLACES LIBÉRÉES !*"
    
    def construire_bloc(liste, titre_semaine):
        if not liste: return ""
        separateur = "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─\n"
        bloc = f"\n📅 *{titre_semaine}*\n{separateur}"
        for a in liste:
            date_rel = formater_date_relative(a['date'])
            nom_sport = a['nom'].upper()
            # Alignement strict (Date 12 car | Horaire 13 car)
            details = f"{date_rel:<12} | {a['horaire']:<13} | {a['places']}pl"
            bloc += f"🏋️ *{nom_sport}*\n```{details}```\n{separateur}"
        return bloc

    corps_whatsapp = construire_bloc(semaine_actuelle, "Cette semaine")
    corps_whatsapp += construire_bloc(semaine_prochaine, "Semaine prochaine")
    
    msg_whatsapp = f"{titre}\n{corps_whatsapp}\n🔗 {URL_UCPA}"
    
    # Envoi GreenAPI (WhatsApp)
    if GREEN_API_URL and WHATSAPP_CHAT_ID:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg_whatsapp}, timeout=10)
        except Exception as e: 
            logging.error(f"❌ Erreur GreenAPI: {e}")

    # Envoi Email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVERS:
        try:
            # Nettoyage Markdown pour l'email
            msg_email = msg_whatsapp.replace('*', '').replace('```', '').replace('─', '-')
            m = MIMEMultipart()
            m['Subject'] = titre.replace('*', '')
            m.attach(MIMEText(msg_email, 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
        except Exception as e: 
            logging.error(f"❌ Erreur Email: {e}")

# --- MOTEUR D'EXTRACTION API ---

def fetch_api_week(date_cible):
    params = {
        'reservationPeriod': '1',
        'espace': 'area_1680850484_13e5a1d0-d511-11ed-93bb-77fd2e78b8a9',
        'time': date_cible,
        '__amp_source_origin': '[https://www.ucpa.com](https://www.ucpa.com)'
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
                horaire = f"{item.get('startTime', '??h??')} - {item.get('endTime', '??h??')}"
                start_date_raw = item.get('startDate', '')
                date_fr = f"{start_date_raw.split('/')[0]}/{start_date_raw.split('/')[1]}" if '/' in start_date_raw else "??/??"
                places = int(item.get('stock', 0))
                
                found_courses.append({
                    "nom": nom, "date": date_fr, "horaire": horaire,
                    "places": places, "statut": "LIBRE" if places > 0 else "COMPLET"
                })
    except Exception as e:
        logging.error(f"⚠️ Erreur extraction JSON : {e}")
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Scan UCPA (Semaine en cours + suivante)...")
    maintenant = datetime.now()
    
    tous_les_cours = []
    try:
        json_s1 = fetch_api_week(maintenant.strftime("%d-%m-%Y"))
        json_s2 = fetch_api_week((maintenant + timedelta(days=7)).strftime("%d-%m-%Y"))
        tous_les_cours.extend(extract_courses_from_api(json_s1))
        tous_les_cours.extend(extract_courses_from_api(json_s2))
    except Exception as e:
        logging.error(f"❌ Erreur API : {e}")
        return

    history = load_and_clean_history()
    today_str = maintenant.strftime("%Y-%m-%d")
    notifs_faites = history.get(today_str, [])

    # Filtrage selon COURS_SURVEILLES
    cours_suivis = [c for c in tous_les_cours if not COURS_SURVEILLES or any(m in c['nom'].lower() for m in COURS_SURVEILLES)]

    # Mémoire des états précédents
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    alertes = []
    for c in cours_suivis:
        uid = f"{c['nom']}|{c['date']}|{c['horaire']}"
        if c['statut'] == "LIBRE":
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == uid for a in anciens_complets)
            if etait_complet and uid not in notifs_faites:
                alertes.append(c)
                notifs_faites.append(uid)

    if alertes:
        send_final_notification(alertes)
        history[today_str] = notifs_faites
        save_history(history)
    
    # Mise à jour mémoire complets
    nouveaux_complets = [c for c in cours_suivis if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
