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

URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')

def get_rendered_content(url):
    logging.info(f"🌐 Initialisation du navigateur pour : {url}")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        
        # --- ÉTAPE 1 : ATTENTE DU RENDU JS ---
        # On attend spécifiquement qu'un élément contenant "####" ou une activité apparaisse
        # Cela prouve que le moteur de template JS a fini son travail
        logging.info("⏳ Attente de l'évaluation du code JS sur la page...")
        wait = WebDriverWait(driver, 20)
        
        # On attend que le conteneur des sessions soit chargé et non vide
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '####')]")))
        
        # --- ÉTAPE 2 : SIMULATION D'INTERACTION ---
        # Scroll lent pour charger tous les créneaux (Lazy Loading fréquent sur ces calendriers)
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1)

        # Récupération finale du texte après rendu complet
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text

    except Exception as e:
        logging.error(f"❌ Erreur lors de l'extraction : {e}")
        # En cas d'erreur, on tente quand même de récupérer ce qui est visible
        return driver.find_element(By.TAG_NAME, "body").text if driver else ""
    finally:
        if driver:
            driver.quit()

def analyze_with_regex(raw_text):
    """Analyse chirurgicale basée sur la structure injectée par le JS"""
    cours_extraits = []
    maintenant = datetime.now()
    
    # Artifact de debug : sauvegarde immédiate du contenu brut
    with open("debug_raw_content.txt", "w", encoding="utf-8") as f:
        f.write(f"--- SOURCE DATA DUMP {maintenant} ---\n")
        f.write(raw_text)

    # Regex pour isoler les blocs de dates (ex: "12 jeu.")
    # On cherche 2 chiffres suivis d'un jour abrégé
    pattern_date = r"(\d{2})\s+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)"
    
    # Regex pour capturer les cours à l'intérieur d'un bloc jour
    # Structure : * HHhMM - HHhMM #### Nom_du_Cours Statut
    pattern_cours = r"\*\s+(\d{1,2}h\d{2})\s+-\s+\d{1,2}h\d{2}\s+####\s+([^ \n].+?)\s{2,}(.+)"

    sections = re.split(pattern_date, raw_text)
    
    # Le premier élément est le header du site, on commence à l'index 1
    for i in range(1, len(sections), 3):
        try:
            jour_num = sections[i]
            # On construit la date (ex: 12/02)
            mois = maintenant.month
            # Si le numéro de jour est très petit alors qu'on est en fin de mois, c'est le mois suivant
            if int(jour_num) < maintenant.day and maintenant.day > 25:
                mois = (maintenant.month % 12) + 1
            
            date_str = f"{jour_num}/{str(mois).zfill(2)}"
            contenu_du_jour = sections[i+2]
            
            matches = re.finditer(pattern_cours, contenu_du_jour)
            for m in matches:
                statut_brut = m.group(3).lower()
                cours_extraits.append({
                    "nom": m.group(2).strip(),
                    "date": date_str,
                    "horaire": m.group(1),
                    "statut": "COMPLET" if "complet" in statut_brut else "LIBRE"
                })
        except Exception as e:
            logging.debug(f"Erreur de parsing sur une section : {e}")
            continue
            
    return cours_extraits

def run_scan():
    raw_content = get_rendered_content(URL_CIBLE)
    
    if not raw_content:
        logging.error("❌ Aucune donnée récupérée.")
        return

    cours = analyze_with_regex(raw_content)
    logging.info(f"📊 {len(cours)} créneaux identifiés après rendu JS.")

    # Gestion de la mémoire (Fichier JSON)
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    nouveaux_complets = []
    alertes = []

    # Affichage et Comparaison
    print(f"\n{'ETAT':<5} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 75)

    for c in cours:
        if c['statut'] == "COMPLET":
            nouveaux_complets.append(c)
            print(f"🔴    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']}")
        else:
            # Vérification si le cours vient de se libérer
            etait_dans_memo = any(
                a['nom'] == c['nom'] and a['date'] == c['date'] and a['horaire'] == c['horaire']
                for a in anciens_complets
            )
            if etait_dans_memo:
                alertes.append(c)
                print(f"🚨    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']} (LIBÉRÉ !)")
            else:
                print(f"🟢    | {c['date']:<6} | {c['horaire']:<10} | {c['nom']}")

    # Sauvegarde des nouveaux cours complets pour le prochain scan
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)

    # Envoi des alertes WhatsApp si nécessaire
    if alertes and GREEN_API_URL and WHATSAPP_ID:
        for a in alertes:
            msg = f"🚨 PLACE LIBRE !\n🏋️ {a['nom']}\n📅 {a['date']} à {a['horaire']}\n🔗 {URL_CIBLE}"
            try:
                requests.post(GREEN_API_URL, json={"chatId": WHATSAPP_ID, "message": msg})
                logging.info(f"📱 Alerte envoyée pour {a['nom']}")
            except:
                logging.error("❌ Échec de l'envoi WhatsApp")

if __name__ == "__main__":
    run_scan()
