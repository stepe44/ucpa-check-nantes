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

# Secrets
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- OUTILS DE GESTION DE LA MÉMOIRE (inchangés) ---

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
        except Exception as e: logging.error(f"❌ Erreur Email: {e}")

# --- NOUVEAU MOTEUR D'EXTRACTION VIA API ---

def fetch_api_week(date_cible):
    """Interroge l'API UCPA pour une date donnée (format JJ-MM-AAAA)."""
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
    
    # ⚠️ NOTE IMPORTANTE : La structure du JSON de l'UCPA peut varier.
    # Ici on fait une supposition de la structure. 
    # S'il y a une erreur d'extraction, jette un oeil au fichier debug_ucpa.json généré !
    
    try:
        # On suppose souvent que le JSON contient une liste d'activités ou des jours
        # Si le JSON est directement une liste ou un dico avec une clé 'sessions', on itère :
        items = json_data.get('sessions', json_data) if isinstance(json_data, dict) else json_data
        
        # S'il y a une imbrication par jour :
        if isinstance(items, dict) and 'days' in items:
            items = [session for day in items['days'] for session in day.get('sessions', [])]

        for item in items:
            # === À ADAPTER SELON LE VRAI JSON DE L'UCPA ===
            # Remplace 'name', 'availablePlaces', etc., par les vraies clés si elles sont différentes.
            nom = item.get('title', item.get('name', 'Cours Inconnu'))
            places_restantes = int(item.get('availablePlaces', item.get('places', 0)))
            
            # Extraction de la date et de l'heure (supposée format ISO 'YYYY-MM-DDTHH:MM:SS' ou autre)
            # On va essayer de récupérer une heure de début et fin
            date_debut_str = item.get('start', item.get('startDate', ''))
            
            if not date_debut_str:
                continue

            # Conversion de la date (si c'est du ISO 8601 : 2026-03-23T18:00:00)
            try:
                dt_obj = datetime.fromisoformat(date_debut_str.replace('Z', '+00:00'))
                date_fr = dt_obj.strftime("%d/%m")
                horaire = dt_obj.strftime("%Hh%M")
            except:
                date_fr = "??/??"
                horaire = "??h??"

            statut = "LIBRE" if places_restantes > 0 else "COMPLET"
            
            found_courses.append({
                "nom": nom,
                "date": date_fr,
                "horaire": horaire,
                "places": places_restantes,
                "statut": statut
            })

    except Exception as e:
        logging.error(f"⚠️ Erreur de parsing JSON : {e}. Regarde le fichier debug_ucpa.json")
        
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run():
    logging.info("🌐 Scan de l'API UCPA pour cette semaine et la semaine prochaine...")
    
    maintenant = datetime.now()
    date_semaine_1 = maintenant.strftime("%d-%m-%Y")
    date_semaine_2 = (maintenant + timedelta(days=7)).strftime("%d-%m-%Y")

    tous_les_cours = []

    try:
        # Appel API Semaine 1
        json_s1 = fetch_api_week(date_semaine_1)
        # Appel API Semaine 2
        json_s2 = fetch_api_week(date_semaine_2)

        # 🛠️ DEBUG : On sauvegarde le brut pour que tu puisses voir la structure la 1ère fois
        with open('debug_ucpa.json', 'w', encoding='utf-8') as f:
            json.dump({"semaine1": json_s1}, f, indent=4, ensure_ascii=False)

        tous_les_cours.extend(extract_courses_from_api(json_s1))
        tous_les_cours.extend(extract_courses_from_api(json_s2))

    except Exception as e:
        logging.error(f"❌ Erreur réseau ou API : {e}")
        return

    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours extrait du JSON. Ouvre 'debug_ucpa.json' pour vérifier les vrais noms des variables ! (ex: title, start, available...)")
        return

    # Suite habituelle de ton algorithme
    history = load_and_clean_history()
    today_str = datetime.now().strftime("%Y-%m-%d")
    notifs_deja_faites_aujourdhui = history.get(today_str, [])

    cours_suivis_actuels = [c for c in tous_les_cours if not COURS_SURVEILLES or any(m in c['nom'].lower() for m in COURS_SURVEILLES)]

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
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_unique for a in anciens_complets)
            pas_encore_notifie = id_unique not in notifs_deja_faites_aujourdhui

            if etait_complet and pas_encore_notifie:
                nouvelles_places_a_notifier.append(c)
                notifs_deja_faites_aujourdhui.append(id_unique)

    if nouvelles_places_a_notifier:
        logging.info(f"🚀 {len(nouvelles_places_a_notifier)} alerte(s) à envoyer !")
        send_final_notification(nouvelles_places_a_notifier)
        history[today_str] = notifs_deja_faites_aujourdhui
        save_history(history)
    else:
        logging.info("ℹ️ Rien à notifier (déjà fait aujourd'hui ou pas de changement).")

    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
