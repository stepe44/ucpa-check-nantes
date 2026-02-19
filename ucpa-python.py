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

# L'URL UCPA originale et son passage via Jina pour le rendu JS dynamique
URL_UCPA = 'https://www.ucpa.com/sport-station/nantes/fitness'
URL_CIBLE = f'https://r.jina.ai/{URL_UCPA}'
MEMO_FILE = 'memoire_ucpa.json'

# --- RÉCUPÉRATION DES SECRETS (Variables d'environnement) ---
# GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_CHAT_ID = os.getenv('WHATSAPP_CHAT_ID')
EMAIL_SENDER = os.getenv('EMAIL_SENDER')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_RECEIVERS = [r.strip() for r in os.getenv('EMAIL_RECEIVER', '').split(',') if r.strip()]

# Filtre : noms de cours en minuscule, séparés par des virgules
raw_filter = os.getenv('COURS_SURVEILLES', '')
COURS_SURVEILLES = [c.strip().lower() for c in raw_filter.split(',') if c.strip()] if raw_filter else []

# --- FONCTIONS DE NOTIFICATION ---

def send_alerts(course):
    """Envoie une alerte sur WhatsApp et par Email"""
    msg = (f"🚨 *PLACE LIBRE !*\n\n"
           f"🏋️ *{course['nom']}*\n"
           f"📅 {course['date']}\n"
           f"⏰ {course['horaire']}\n"
           f"🔥 {course['places']} places restantes !\n"
           f"🔗 {URL_UCPA}")
    
    # 1. WhatsApp (Green API)
    if GREEN_API_URL:
        try:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_CHAT_ID, "message": msg}, timeout=10)
        except Exception as e:
            logging.error(f"Erreur WhatsApp : {e}")
        
    # 2. Email (SMTP Gmail)
    if EMAIL_SENDER and EMAIL_PASSWORD:
        try:
            m = MIMEMultipart()
            m['Subject'] = f"🚨 Place Libérée : {course['nom']} ({course['date']})"
            m.attach(MIMEText(msg.replace('*', ''), 'plain'))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(EMAIL_SENDER, EMAIL_PASSWORD)
                s.sendmail(EMAIL_SENDER, EMAIL_RECEIVERS, m.as_string())
        except Exception as e:
            logging.error(f"Erreur Email : {e}")

# --- MOTEUR D'EXTRACTION (ANALYSE LIGNE PAR LIGNE) ---

def parse_jina_markdown(markdown_text):
    """
    Extrait les cours du Markdown Jina. 
    L'analyse ligne par ligne garantit de ne rater aucun doublon horaire.
    """
    found_courses = []
    maintenant = datetime.now()
    
    # On découpe le contenu par bloc de jour pour attribuer la bonne date
    # Cherche par exemple : "20 ven." ou "21 sam."
    sections = re.split(r"(\d{2}\s+(?:lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.))", markdown_text, flags=re.IGNORECASE)
    
    for i in range(1, len(sections), 2):
        jour_num = sections[i].strip().split(' ')[0]
        bloc_contenu = sections[i+1]
        
        # Détermination du mois (gestion du passage au mois suivant)
        m_val = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            m_val = (m_val % 12) + 1
        date_cle = f"{jour_num}/{str(m_val).zfill(2)}"

        # Analyse de chaque ligne pour trouver le motif horaire #### Nom
        lines = bloc_contenu.split('\n')
        for line in lines:
            if '####' not in line:
                continue
            
            # 1. Extraction de l'horaire
            match_h = re.search(r"(\d{2}h\d{2}\s*-\s*\d{2}h\d{2})", line)
            if not match_h:
                continue
            horaire = match_h.group(1).strip()
            
            # 2. Extraction du reste de la ligne (nom et statut)
            nom_part = line.split('####')[1].strip()
            
            # 3. Détection des places ou du statut "Complet"
            p_match = re.search(r"(\d+)\s*places? restantes", nom_part)
            p_val = int(p_match.group(1)) if p_match else 0
            
            # Nettoyage du nom pour enlever le statut et les liens Markdown [RÉSERVER](...)
            nom_clean = re.sub(r"(\d+)\s*places? restantes|Complet|\[RÉSERVER\].*", "", nom_part).strip()
            
            statut = "LIBRE" if p_val > 0 else "COMPLET" if "Complet" in nom_part else None
            
            if statut:
                found_courses.append({
                    "nom": nom_clean,
                    "date": date_cle,
                    "horaire": horaire,
                    "places": p_val,
                    "statut": statut
                })
    return found_courses

# --- LOGIQUE PRINCIPALE ---

def run_scan():
    logging.info(f"🔍 Scan lancé sur : {URL_CIBLE}")
    
    try:
        # Récupération du Markdown pré-rendu par Jina
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(URL_CIBLE, headers=headers, timeout=30)
        response.raise_for_status()
        content = response.text
    except Exception as e:
        logging.error(f"❌ Erreur lors de la récupération : {e}")
        return

    # Extraction des données
    tous_les_cours = parse_jina_markdown(content)
    
    if not tous_les_cours:
        logging.warning("⚠️ Aucun cours n'a été extrait. Vérifiez la structure du Markdown.")
        return

    # Tri par date et heure
    tous_les_cours.sort(key=lambda x: (x['date'], x['horaire']))

    # --- AFFICHAGE DU TABLEAU POUR DEBUG ---
    header = f"{'DATE':<6} | {'HEURE':<15} | {'STATUT':<8} | {'PL.':<3} | {'SUIVI':<5} | {'NOM'}"
    sep = "-" * 105
    print(f"\n{sep}\n{header}\n{sep}")
    
    stats_jour = defaultdict(lambda: {"total": 0, "complets": 0})
    cours_suivis_actuels = []

    for c in tous_les_cours:
        # Vérification si le cours est dans la liste surveillée
        est_suivi = any(m in c['nom'].lower() for m in COURS_SURVEILLES) if COURS_SURVEILLES else True
        
        # Mise à jour des compteurs par jour
        stats_jour[c['date']]["total"] += 1
        if c['statut'] == "COMPLET":
            stats_jour[c['date']]["complets"] += 1
            
        # Affichage ligne
        suivi_tag = "[X]" if est_suivi else "[ ]"
        print(f"{c['date']:<6} | {c['horaire']:<15} | {c['statut']:<8} | {c['places']:<3} | {suivi_tag:<5} | {c['nom']}")
        
        if est_suivi:
            cours_suivis_actuels.append(c)

    print(f"{sep}\n")
    
    # Affichage du résumé par jour pour confirmation
    for j, s in sorted(stats_jour.items()):
        logging.info(f"📊 {j} : {s['total']} cours détectés | {s['complets']} complets")
    logging.info("==========================================")

    # --- MÉMOIRE ET ALERTES ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except:
            pass

    # Détection des places libérées (Était COMPLET avant, est LIBRE maintenant)
    for c in cours_suivis_actuels:
        if c['statut'] == "LIBRE":
            # Identifiant unique du cours
            id_c = f"{c['nom']}|{c['date']}|{c['horaire']}"
            if any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_c for a in anciens_complets):
                logging.info(f"🚀 ALERTE : Place libérée pour {c['nom']} !")
                send_alerts(c)

    # Mise à jour du fichier mémoire avec les cours complets actuels (uniquement ceux suivis)
    nouveaux_complets = [c for c in cours_suivis_actuels if c['statut'] == "COMPLET"]
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    logging.info(f"💾 Mémoire mise à jour ({len(nouveaux_complets)} cours complets surveillés).")

if __name__ == "__main__":
    try:
        run_scan()
    except Exception as e:
        logging.error(f"Erreur critique : {e}")
