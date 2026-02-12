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

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Ouverture de Chrome pour : {url}")
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(5)  # Pause forcée pour le rendu JS initial
        
        # Scroll pour déclencher le chargement lazy-load
        driver.execute_script("window.scrollTo(0, 1500);")
        time.sleep(3)
        
        # On récupère le texte visible
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        if not raw_text or len(raw_text) < 100:
            logging.warning("⚠️ Le texte extrait semble vide. Tentative de récupération du HTML source.")
            return driver.page_source # Si le texte échoue, on renvoie le HTML
            
        return raw_text
    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_regex(raw_text):
    # Affiche un extrait du texte reçu pour debug dans la console
    print("\n" + "="*50)
    print("--- APERÇU DU TEXTE EXTRAIT (1000 premiers caractères) ---")
    print(raw_text[:1000])
    print("="*50 + "\n")

    cours_extraits = []
    maintenant = datetime.now()
    
    # Pattern pour les blocs jours (ex: "12 jeu.")
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    # Pattern pour les lignes de cours
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ ].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    if len(sections) < 2:
        print("❌ La Regex de date n'a trouvé aucune correspondance.")
        return []

    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        date_str = f"{jour_num}/{str(maintenant.month).zfill(2)}"
        contenu_du_jour = sections[i+2]
        
        matches = re.finditer(pattern_cours, contenu_du_jour)
        for m in matches:
            cours_extraits.append({
                "nom": m.group(2).strip(),
                "date": date_str,
                "horaire": m.group(1),
                "statut": "COMPLET" if "complet" in m.group(3).lower() else "LIBRE"
            })
            
    return cours_extraits

def run_scan():
    raw = get_heavy_selenium_content(URL_CIBLE)
    
    # Sauvegarde forcée dans le dossier courant
    try:
        with open("debug_page.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"✅ Fichier 'debug_page.txt' créé avec succès ({len(raw)} caractères).")
    except Exception as e:
        print(f"❌ Impossible de créer le fichier debug : {e}")

    cours = analyze_with_regex(raw)
    
    if not cours:
        print("⚠️ Aucun cours trouvé. Vérifiez 'debug_page.txt' pour voir la structure réelle.")
    else:
        print(f"✅ {len(cours)} cours extraits avec succès.")
        for c in cours[:5]: # Affiche les 5 premiers pour test
            print(f"   - {c['date']} {c['horaire']} : {c['nom']} ({c['statut']})")

if __name__ == "__main__":
    run_scan()
