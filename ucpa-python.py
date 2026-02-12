import os
import json
import time
import re
import requests
import logging
from datetime import datetime

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
MEMO_FILE = 'memoire_ucpa.json'

def analyze_vertical_data(raw_text):
    """Analyse les données structurées verticalement (Jour > Nom > Heure > Statut)"""
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    cours_extraits = []
    
    current_day_num = None
    jours_semaine = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
    maintenant = datetime.now()

    # On parcourt les lignes
    for i in range(len(lines)):
        ligne = lines[i]

        # 1. Détection du jour (ex: "jeudi" suivi de "12")
        if ligne.lower() in jours_semaine:
            if i + 1 < len(lines) and lines[i+1].isdigit():
                current_day_num = lines[i+1].zfill(2)
                continue

        # 2. Détection d'un créneau horaire (ex: "17h30 - 18h15")
        if re.match(r"\d{1,2}h\d{2}\s*-\s*\d{1,2}h\d{2}", ligne):
            if current_day_num:
                # Le nom du cours est TOUJOURS la ligne juste AVANT l'heure
                nom_cours = lines[i-1]
                
                # Le statut est la ligne juste APRÈS l'heure
                # Mais attention, si c'est "RÉSERVER", le statut est encore la ligne d'après
                statut_brut = ""
                if i + 1 < len(lines):
                    if lines[i+1] == "RÉSERVER":
                        statut_brut = lines[i+2] if i + 2 < len(lines) else ""
                    else:
                        statut_brut = lines[i+1]

                statut = "COMPLET" if "complet" in statut_brut.lower() else "LIBRE"
                
                # Construction de la date
                mois = maintenant.month
                if int(current_day_num) < maintenant.day and maintenant.day > 25:
                    mois = (maintenant.month % 12) + 1
                
                cours_extraits.append({
                    "nom": nom_cours,
                    "date": f"{current_day_num}/{str(mois).zfill(2)}",
                    "horaire": ligne.split('-')[0].strip(),
                    "statut": statut
                })

    return cours_extraits

def run_scan():
    # --- 1. RÉCUPÉRATION (Utilise ton moteur blindé Selenium ici) ---
    # Pour l'exemple, on suppose que 'raw_content' est le texte que tu m'as donné
    # raw_content = get_heavy_selenium_content(URL_CIBLE) 
    # ... (code selenium) ...
    
    # Simulation du contenu pour le test
    from __main__ import raw_content_variable # ou appel direct
    
    cours_actuels = analyze_vertical_data(raw_content_variable)
    logging.info(f"🔎 {len(cours_actuels)} cours identifiés.")

    # --- 2. CHARGEMENT MÉMOIRE ---
    anciens_complets = []
    if os.path.exists(MEMO_FILE):
        try:
            with open(MEMO_FILE, 'r', encoding='utf-8') as f:
                anciens_complets = json.load(f)
        except: pass

    # --- 3. COMPARAISON ET ALERTES ---
    nouveaux_complets = []
    alertes_liberation = []

    print(f"\n{'ETAT':<5} | {'DATE':<6} | {'HEURE':<8} | {'COURS'}")
    print("-" * 60)

    for c in cours_actuels:
        # Identifiant unique pour comparer
        id_cours = f"{c['nom']}|{c['date']}|{c['horaire']}"
        
        if c['statut'] == "COMPLET":
            nouveaux_complets.append(c)
            print(f"🔴    | {c['date']:<6} | {c['horaire']:<8} | {c['nom']}")
        else:
            # Si LIBRE, on regarde s'il était dans la liste des COMPLET avant
            etait_complet = any(f"{a['nom']}|{a['date']}|{a['horaire']}" == id_cours 
                                for a in anciens_complets)
            
            if etait_complet:
                alertes_liberation.append(c)
                print(f"🚨    | {c['date']:<6} | {c['horaire']:<8} | {c['nom']} --> LIBRE !")
            else:
                print(f"🟢    | {c['date']:<6} | {c['horaire']:<8} | {c['nom']}")

    # --- 4. ENVOI DES ALERTES WHATSAPP ---
    if alertes_liberation and GREEN_API_URL and WHATSAPP_ID:
        for a in alertes_liberation:
            message = (f"🚨 *PLACE LIBÉRÉE !*\n\n"
                       f"🏋️ *Cours :* {a['nom']}\n"
                       f"📅 *Date :* {a['date']}\n"
                       f"🕒 *Heure :* {a['horaire']}\n"
                       f"🔗 _Vite :_ {URL_CIBLE}")
            
            try:
                requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_ID, "message": message}, timeout=10)
                logging.info(f"📱 Alerte envoyée pour {a['nom']}")
            except Exception as e:
                logging.error(f"❌ Erreur envoi WhatsApp : {e}")

    # --- 5. MISE À JOUR DE LA MÉMOIRE ---
    with open(MEMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info(f"💾 Mémoire mise à jour avec {len(nouveaux_complets)} cours complets.")

if __name__ == "__main__":
    run_scan()
