import os
import json
import time
import re
import requests
import logging
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- CONFIGURATION ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

MOIS_MAP = {
    'janvier': '01', 'février': '02', 'mars': '03', 'avril': '04',
    'mai': '05', 'juin': '06', 'juillet': '07', 'août': '08',
    'septembre': '09', 'octobre': '10', 'novembre': '11', 'décembre': '12'
}

def send_whatsapp(message):
    if not GREEN_API_URL or not WHATSAPP_ID: return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_schedule_data(url):
    logging.info(f"🌐 Analyse du site : {url}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    cours_extraits = []
    
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "p-program-list")))
        
        full_text = driver.find_element(By.TAG_NAME, "body").text
        
        # Le Regex capture maintenant le JOUR (Group 1)
        date_pattern = r"(LUNDI|MARDI|MERCREDI|JEUDI|VENDREDI|SAMEDI|DIMANCHE)\s(\d{1,2})\s([^\n\s]+)"
        blocks = re.split(date_pattern, full_text, flags=re.IGNORECASE)
        
        for i in range(1, len(blocks), 4):
            jour_nom = blocks[i].capitalize() # Ex: "Lundi"
            jour_num = blocks[i+1].zfill(2)
            mois_nom = blocks[i+2].lower().strip()
            mois_num = MOIS_MAP.get(mois_nom, "01")
            
            date_formattee = f"{jour_num}/{mois_num}"
            contenu_jour = blocks[i+3]
            
            cours_patterns = re.findall(r"(\d{1,2}[:h]\d{2}).*?\n(.*?)\n.*?(COMPLET|places restantes|Réserver|S'inscrire)", contenu_jour, re.DOTALL)
            
            for horaire, nom, statut_raw in cours_patterns:
                statut = "COMPLET" if "COMPLET" in statut_raw.upper() else "LIBRE"
                
                cours_extraits.append({
                    "nom": nom.strip(),
                    "jour": jour_nom, # Nouveau champ ajouté
                    "date": date_formattee,
                    "horaire": horaire.replace(':', 'h'),
                    "statut": statut
                })
                
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
    finally:
        driver.quit()
    
    return cours_extraits

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT ---")
    
    cours = get_schedule_data(URL_CIBLE)
    if not cours: return

    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    maintenant = datetime.now()
    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'JOUR':<10} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 75)

    for c in cours:
        nom = c['nom']
        jour = c['jour']
        d_raw = c['date']
        h_raw = c['horaire']
        statut = c['statut']

        # Logique de filtrage des dates passées
        try:
            parts = d_raw.split('/')
            date_objet = datetime(maintenant.year, int(parts[1]), int(parts[0])).date()
            if date_objet < maintenant.date(): continue
        except: continue

        if statut == "COMPLET":
            nouveaux_complets.append(c)
            icon = "🔴"
        else:
            icon = "🟢"
            # Détection de libération
            etait_complet = any(
                a.get('nom','').strip().lower() == nom.lower() and 
                a.get('date') == d_raw and 
                a.get('horaire') == h_raw
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)
                icon = "🚨"

        print(f"{icon} {statut:<8} | {jour:<10} | {d_raw:<6} | {h_raw:<10} | {nom}")

    if alertes:
        for c in alertes:
            # Formatage du message avec le jour inclus
            msg = f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('jour')} {c.get('date')} à {c.get('horaire')}"
            send_whatsapp(msg)

    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info(f"🏁 Scan fini. Mémoire : {len(nouveaux_complets)} cours suivis.")

if __name__ == "__main__":
    run_scan()
