import os
import json
import time
import re
import requests
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Lancement du moteur furtif pour : {url}")
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(options=options)
    try:
        # Masquage de la propriété webdriver
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
        
        driver.get(url)
        
        # Scroll progressif pour déclencher le chargement des cours
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.5)
        
        driver.execute_script("window.scrollTo(0, 0);")

        # Attente du rendu métier (max 20s)
        try:
            WebDriverWait(driver, 20).until(lambda d: 
                "restantes" in d.find_element(By.TAG_NAME, "body").text.lower() or 
                "complet" in d.find_element(By.TAG_NAME, "body").text.lower()
            )
        except: 
            logging.warning("⚠️ Timeout atteint, tentative d'extraction malgré tout.")
        
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_logic(raw_text):
    # Sauvegarde du dump pour analyse sur GitHub Artifacts
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)
    
    cours_extraits = []
    maintenant = datetime.now()
    
    # 1. Split par date (ex: 12 jeu.)
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    # 2. Capture du cours (Heure #### Nom Statut)
    pattern_cours = r"(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ \n].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    for i in range(1, len(sections), 3):
        jour = sections[i]
        mois = maintenant.month
        # Correction mois suivant
        if int(jour) < maintenant.day and maintenant.day > 25:
            mois = (maintenant.month % 12) + 1
            
        date_str = f"{jour}/{str(mois).zfill(2)}"
        content = sections[i+2]
        
        for m in re.finditer(pattern_cours, content):
            statut_info = m.group(3).lower()
            cours_extraits.append({
                "date": date_str,
                "horaire": m.group(1),
                "nom": m.group(2).strip(),
                "statut": "COMPLET" if "complet" in statut_info else "LIBRE"
            })
    return cours_extraits

def run_scan():
    raw = get_heavy_selenium_content(URL_CIBLE)
    if not raw: return
    
    cours = analyze_logic(raw)
    logging.info(f"✅ {len(cours)} cours trouvés.")
    
    # Sauvegarde JSON pour comparaison
    with open("data_extracted.json", "w", encoding="utf-8") as f:
        json.dump(cours, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run_scan()
