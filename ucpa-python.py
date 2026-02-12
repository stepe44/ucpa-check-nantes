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

# --- CONFIGURATION LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- VARIABLES D'ENVIRONNEMENT ---
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def send_whatsapp(message):
    if not GREEN_API_URL or not WHATSAPP_ID: return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Lancement du navigateur pour : {url}")
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"})
        driver.get(url)
        
        # Scroll progressif pour forcer le chargement du JS UCPA
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.4)
            
        # Attente que les données de créneaux soient visibles
        try:
            WebDriverWait(driver, 15).until(
                lambda d: "####" in d.find_element(By.TAG_NAME, "body").text
            )
        except:
            pass
            
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    """
    Analyse le texte brut UCPA par blocs de jours.
    Extrait le nom du cours via les marqueurs '####' et l'heure via le pattern '*'
    """
    cours_extraits = []
    maintenant = datetime.now()
    
    # Étape 1 : Découper par jour (ex: "09 lun.", "10 mar.")
    # On cherche 2 chiffres suivis d'un jour abrégé
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    
    # Étape 2 : Pattern pour capturer un cours
    # Groupe 1: Heure | Groupe 2: Nom du cours | Groupe 3: Statut/Reste
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ ].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    # Re-split donne une liste : [texte_avant, "09", "lun.", texte_apres, "10", "mar.", ...]
    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        
        # Logique simple de gestion de mois (si jour extrait < jour actuel, on passe probablement au mois suivant)
        mois_objet = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois_objet = (maintenant.month % 12) + 1
        
        date_str = f"{jour_num}/{str(mois_objet).zfill(2)}"
        contenu_du_jour = sections[i+2]
        
        matches = re.finditer(pattern_cours, contenu_du_jour)
        for m in matches:
            horaire = m.group(1).replace(' ', '')
            nom = m.group(2).strip()
            indicateur_statut = m.group(3).lower()
            
            statut = "COMPLET" if "complet" in indicateur_statut else "LIBRE"
            
            cours_extraits.append({
                "nom": nom,
                "date": date_str,
                "horaire": horaire,
                "statut": statut
            })
            
    return cours_extraits

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT (MOTEUR REGEX) ---")
    raw = get_heavy_selenium_content(URL_CIBLE)
    
    # --- AJOUT : CAPTURE DU LOG COMPLET POUR ANALYSE ---
    if raw:
        with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
            f.write(f"--- CAPTURE DU {datetime.now()} ---\n")
            f.write(raw)
        logging.info("💾 Contenu brut sauvegardé dans 'debug_raw_content.txt' pour analyse.")
    # --------------------------------------------------

    if not raw or "####" not in raw:
        logging.warning("⚠️ Données UCPA non détectées dans le texte brut.")
        # On ne s'arrête pas forcément ici pour permettre l'analyse du fichier debug
        if not raw: return

    cours = analyze_with_regex(raw)
    
    # ... reste du code identique ...
    if not cours:
        logging.warning("⚠️ Aucun cours trouvé après analyse Regex.")
        return

