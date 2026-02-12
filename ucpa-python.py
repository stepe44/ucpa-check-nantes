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

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')

def send_whatsapp(message):
    if not GREEN_API_URL or not WHATSAPP_ID: return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Scan Selenium : {url}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(5) # Attente du rendu JS
        driver.execute_script("window.scrollTo(0, 2000);")
        time.sleep(2)
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    """Analyse basée sur ton exemple de données réelles"""
    cours_extraits = []
    maintenant = datetime.now()
    
    # 1. Découpage par bloc de jour (ex: 09 lun., 10 mar.)
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    
    # 2. Capture des cours (Heure - Heure #### Nom Statut)
    # On capture l'heure, le nom (après ####) et le reste (statut)
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ \n].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    # sections[i] = jour (09), sections[i+1] = nom_jour (lun.), sections[i+2] = contenu
    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        # Déduction du mois (gestion basique du passage au mois suivant)
        mois = maintenant.month
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois = (maintenant.month % 12) + 1
        
        date_str = f"{jour_num}/{str(mois).zfill(2)}"
        contenu_jour = sections[i+2]
        
        matches = re.finditer(pattern_cours, contenu_jour)
        for m in matches:
            horaire = m.group(1)
            nom = m.group(2).strip()
            statut_brut = m.group(3).lower()
            
            statut = "COMPLET" if "complet" in statut_brut else "LIBRE"
            
            cours_extraits.append({
                "nom": nom,
                "date": date_str,
                "horaire": horaire,
                "statut": statut
            })
            
    return cours_extraits

def run_scan():
    raw = get_heavy_selenium_content(URL_CIBLE)
    
    # --- ARTIFACT 1 : LOG DU CONTENU BRUT ---
    if raw:
        with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
            f.write(f"--- CAPTURE DU {datetime.now()} ---\n")
            f.write(raw)
        logging.info("💾 Artifact 'debug_raw_content.txt' créé.")

    cours = analyze_with_regex(raw)
    
    if not cours:
        logging.warning("⚠️ Aucune donnée extraite. Vérifiez 'debug_raw_content.txt'.")
        return

    # --- LOGIQUE DE COMPARAISON ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 70)

    for c in cours:
        icon = "🔴" if c['statut'] == "COMPLET" else "🟢"
        
        if c['statut'] == "COMPLET":
            nouveaux_complets.append(c)
        else:
            # Si c'est LIBRE, on vérifie s'il était COMPLET avant
            etait_complet = any(
                a['nom'] == c['nom'] and a['date'] == c['date'] and a['horaire'] == c['horaire']
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)
                icon = "🚨"

        print(f"{icon} {c['statut']:<8} | {c['date']:<6} | {c['horaire']:<10} | {c['nom']}")

    # --- ARTIFACT 2 : SAUVEGARDE DE LA MÉMOIRE ---
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    logging.info(f"💾 Artifact '{memo_file}' mis à jour.")

    # Alertes
    for a in alertes:
        send_whatsapp(f"🚨 LIBRE : {a['nom']}\n📅 {a['date']} à {a['horaire']}\n🔗 {URL_CIBLE}")

if __name__ == "__main__":
    run_scan()
