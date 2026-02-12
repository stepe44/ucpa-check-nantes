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

# --- VARIABLES D'ENVIRONNEMENT ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
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
    logging.info(f"🌐 Lancement du navigateur blindé pour : {url}")
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    driver = webdriver.Chrome(options=options)
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"})
        driver.get(url)
        # Scroll progressif
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, 0);")
        try:
            WebDriverWait(driver, 20).until(lambda d: "restantes" in d.find_element(By.TAG_NAME, "body").text.lower() or "complet" in d.find_element(By.TAG_NAME, "body").text.lower())
        except: pass
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def clean_and_extract_schedule(raw_text):
    phrase = "Si vous êtes titulaire d'une carte ou de l'abonnement, rendez-vous dans votre espace personnel pour réserver votre séance."
    return raw_text.split(phrase)[1][:15000] if phrase in raw_text else raw_text[:15000]

def analyze_with_gemini(content):
    if not GEMINI_API_KEY: return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"Extrais le planning en JSON strict (liste d'objets) avec : 'nom', 'date' (format DD/MM), 'horaire' (format HHhMM), 'statut' (LIBRE ou COMPLET). Texte : {content}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
        text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except: return []

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT ---")
    raw = get_heavy_selenium_content(URL_CIBLE)
    clean = clean_and_extract_schedule(raw)
    cours = analyze_with_gemini(clean)
    if not cours: 
        logging.warning("⚠️ Aucun cours retourné par Gemini.")
        return

    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    maintenant = datetime.now()
    aujourdhui_date = maintenant.date()
    heure_limite = maintenant - timedelta(minutes=30) # Marge pour les cours qui viennent de commencer

    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 65)

    for c in cours:
        nom = (c.get('nom') or "Inconnu").strip()
        d_raw = c.get('date') or ""
        h_raw = c.get('horaire') or ""
        statut = c.get('statut') or "INCONNU"

        try:
            # 1. Normalisation de la date DD/MM
            parts = d_raw.split('/')
            jour = int(parts[0])
            mois = int(parts[1])
            date_objet = datetime(maintenant.year, mois, jour).date()

            # 2. Normalisation de l'heure
            h_clean = h_raw.lower().replace('h', ':').strip()
            hh, mm = map(int, h_clean.split(':'))
            datetime_cours = datetime(maintenant.year, mois, jour, hh, mm)

            # --- LOGIQUE DE FILTRAGE AMELIORÉE ---
            # On ignore SEULEMENT si la date est strictement avant aujourd'hui
            if date_objet < aujourdhui_date:
                continue
            
            # Si c'est aujourd'hui, on ne retire le cours que s'il est commencé depuis plus de 30 min
            if date_objet == aujourdhui_date and datetime_cours < heure_limite:
                continue

        except Exception as e:
            logging.warning(f"⚠️ Erreur parsing date/heure pour {nom} ({d_raw} {h_raw}): {e}")
            # En cas d'erreur de parsing, on garde le cours par sécurité
            pass

        # --- TRAITEMENT ---
        if statut == "COMPLET":
            nouveaux_complets.append(c)
            icon = "🔴"
        else:
            icon = "🟢"
            # Détection de libération : présent dans l'ancienne mémoire mais LIBRE maintenant
            etait_complet = any(
                a.get('nom','').strip().lower() == nom.lower() and 
                a.get('date') == d_raw and 
                a.get('horaire') == h_raw
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)
                icon = "🚨"

        print(f"{icon} {statut:<8} | {d_raw:<6} | {h_raw:<10} | {nom}")

    # Alertes WhatsApp
    if alertes:
        for c in alertes:
            send_whatsapp(f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('date')} à {c.get('horaire')}\n🔗 {URL_CIBLE}")

    # Sauvegarde
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info(f"🏁 Scan fini. Mémoire : {len(nouveaux_complets)} cours suivis.")

if __name__ == "__main__":
    run_scan()
