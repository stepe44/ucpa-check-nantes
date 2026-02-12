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

def get_rendered_content(url):
    logging.info(f"🌐 Connexion à : {url}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    # User-agent important pour éviter d'être considéré comme un robot basique
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        
        # On attend 10 secondes fixes pour laisser le JS s'exécuter 
        # C'est plus fiable qu'un wait sur un texte qui peut changer
        logging.info("⏳ Chargement des scripts de la page (10s)...")
        time.sleep(10)
        
        # Scroll pour forcer le rendu des éléments hors-champ
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text

    except Exception as e:
        logging.error(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        if driver:
            driver.quit()

def analyze_with_regex(raw_text):
    cours_extraits = []
    maintenant = datetime.now()
    
    # SAUVEGARDE SYSTÉMATIQUE POUR ANALYSE
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(raw_text)
    logging.info("💾 Artifact 'debug_raw_content.txt' mis à jour.")

    # --- REGEX OPTIMISÉE POUR TON EXEMPLE ---
    # Bloc jour : "12 jeu.", "13 ven."
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    
    # Ligne cours : "* 17h30 - 18h15 #### Nom_du_Cours Statut"
    # Modifié pour être plus tolérant sur les espaces
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+(.+?)(?:\s{2,}|\n|$)(.*)"

    sections = re.split(pattern_date, raw_text)
    
    for i in range(1, len(sections), 3):
        jour_num = sections[i]
        mois = maintenant.month
        # Si on détecte des jours du mois suivant
        if int(jour_num) < maintenant.day and maintenant.day > 20:
            mois = (maintenant.month % 12) + 1
            
        date_str = f"{jour_num}/{str(mois).zfill(2)}"
        contenu_jour = sections[i+2]
        
        # On nettoie le contenu pour faciliter la regex
        lignes = contenu_jour.split('\n')
        for ligne in lignes:
            m = re.search(pattern_cours, ligne)
            if m:
                horaire = m.group(1)
                nom = m.group(2).strip()
                reste = m.group(3).lower()
                
                statut = "COMPLET" if "complet" in reste else "LIBRE"
                
                cours_extraits.append({
                    "nom": nom,
                    "date": date_str,
                    "horaire": horaire,
                    "statut": statut
                })
            
    return cours_extraits

def run_scan():
    raw_content = get_rendered_content(URL_CIBLE)
    
    if not raw_content or len(raw_content) < 500:
        logging.error("❌ Contenu insuffisant récupéré. Vérifiez la connexion.")
        return

    cours = analyze_with_regex(raw_content)
    logging.info(f"📊 {len(cours)} créneaux trouvés.")

    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    nouveaux_complets = []
    alertes = []

    print(f"\n{'ETAT':<5} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 70)

    for c in cours:
        key = f"{c['nom']}-{c['date']}-{c['horaire']}"
        
        if c['statut'] == "COMPLET":
            nouveaux_complets.append(c)
            print(f"🔴    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']}")
        else:
            # Check libération
            etait_complet = any(
                a['nom'] == c['nom'] and a['date'] == c['date'] and a['horaire'] == c['horaire']
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)
                print(f"🚨    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']} (LIBRE !)")
            else:
                print(f"🟢    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']}")

    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

    for a in alertes:
        msg = f"🚨 PLACE LIBRE !\n🏋️ {a['nom']}\n📅 {a['date']} à {a['horaire']}\n🔗 {URL_CIBLE}"
        if GREEN_API_URL and WHATSAPP_ID:
            requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_ID, "message": msg})

if __name__ == "__main__":
    run_scan()
