import os
import json
import time
import re
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def get_dynamic_content(url):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # Simulation d'un vrai navigateur pour éviter le blocage "Robot"
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        logging.info(f"🌐 Navigation vers {url}")
        driver.get(url)

        # --- ÉTAPE CRUCIALE : ATTENTE DU RENDU ---
        # On attend que le sélecteur qui contient les cours soit présent ET ne contienne plus d'accolades {{ }}
        wait = WebDriverWait(driver, 30)
        
        # On attend qu'un élément de cours (souvent des <li> ou des <div> spécifiques) soit chargé
        # Ici on cible un texte qui contient "h" (pour l'heure) mais pas d'accolades
        logging.info("⏳ Attente du rendu des templates JS...")
        
        # On attend qu'un élément contenant l'heure (format 12h30) apparaisse
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'h')]")))
        
        # Petit scroll pour déclencher le lazy loading des images/données
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(5) # Temps de sécurité pour l'hydratation finale

        # Extraction via sélecteurs spécifiques plutôt que body.text
        # On récupère tous les éléments qui ressemblent à des lignes de cours
        return driver.find_element(By.TAG_NAME, "body").text

    except Exception as e:
        logging.error(f"❌ Erreur lors du rendu JS : {e}")
        return driver.page_source # Backup
    finally:
        driver.quit()

def analyze_logic(raw_text):
    # Sauvegarde pour artifact GitHub
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)
    
    cours_extraits = []
    maintenant = datetime.now()
    
    # Nouvelle Regex plus flexible pour le format dynamique
    # Elle cherche : Jour -> Heure -> Nom (entre ####) -> Statut
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    pattern_cours = r"(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ \n].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    for i in range(1, len(sections), 3):
        jour = sections[i]
        content = sections[i+2]
        
        for m in re.finditer(pattern_cours, content):
            cours_extraits.append({
                "date": f"{jour}/{str(maintenant.month).zfill(2)}",
                "horaire": m.group(1),
                "nom": m.group(2).strip(),
                "statut": "COMPLET" if "complet" in m.group(3).lower() else "LIBRE"
            })
    return cours_extraits

def run():
    content = get_dynamic_content(URL_CIBLE)
    cours = analyze_logic(content)
    
    print(f"DEBUG: {len(cours)} cours trouvés.")
    for c in cours[:3]: # Print les 3 premiers pour vérification dans les logs GH
        print(f"Found: {c['date']} {c['horaire']} - {c['nom']} [{c['statut']}]")
    
    # Sauvegarde des données structurées
    with open("data_extracted.json", "w", encoding="utf-8") as f:
        json.dump(cours, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    run()
