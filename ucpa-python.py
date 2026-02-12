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
    """Envoie une notification WhatsApp via GreenAPI."""
    if not GREEN_API_URL or not WHATSAPP_ID:
        logging.warning("⚠️ Pas de configuration WhatsApp (Variables manquantes).")
        return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        logging.info("✅ Notification WhatsApp envoyée.")
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_heavy_selenium_content(url):
    """Version d'origine avec scroll complet et anti-détection."""
    logging.info(f"🌐 Lancement du navigateur blindé pour : {url}")
    
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
        
        driver.get(url)
        logging.info("⏳ Page chargée. Début du traitement JS...")

        # 1. SCROLL PROGRESSIF (Origine)
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.5)
        
        driver.execute_script("window.scrollTo(0, 0);")

        # 2. ATTENTE INTELLIGENTE (Origine)
        try:
            WebDriverWait(driver, 20).until(
                lambda d: "restantes" in d.find_element(By.TAG_NAME, "body").text.lower() or 
                          "complet" in d.find_element(By.TAG_NAME, "body").text.lower()
            )
            logging.info("✅ Données détectées.")
        except Exception:
            logging.warning("⚠️ Timeout : Extraction tentée malgré tout.")

        return driver.find_element(By.TAG_NAME, "body").text

    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()

def clean_and_extract_schedule(raw_text):
    """Nettoyage basé sur la phrase d'amorce d'origine."""
    if not raw_text: return ""
    phrase_amorce = "Si vous êtes titulaire d'une carte ou de l'abonnement, rendez-vous dans votre espace personnel pour réserver votre séance."
    
    if phrase_amorce in raw_text:
        clean_text = raw_text.split(phrase_amorce)[1]
    else:
        fragment_court = "rendez-vous dans votre espace personnel"
        clean_text = raw_text.split(fragment_court)[-1] if fragment_court in raw_text else raw_text

    return clean_text[:15000]

def analyze_with_gemini(content):
    """Analyse Gemini avec système de retry d'origine."""
    if not GEMINI_API_KEY: return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse ce texte de planning sportif. Extrais un tableau JSON strict.
    Chaque objet : {{ "nom": "...", "date": "DD/MM", "horaire": "HHhMM", "statut": "LIBRE" ou "COMPLET" }}
    Texte :
    {content}
    """
    
    for attempt in range(3):
        try:
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if resp.status_code == 429:
                time.sleep((attempt + 1) * 15)
                continue
            resp.raise_for_status()
            text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
            json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
            return json.loads(json_match.group(0)) if json_match else []
        except Exception as e:
            logging.error(f"❌ Erreur Gemini (Essai {attempt+1}): {e}")
            time.sleep(5)
    return []

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT ---")
    
    raw = get_heavy_selenium_content(URL_CIBLE)
    if not raw: return

    clean = clean_and_extract_schedule(raw)
    cours = analyze_with_gemini(clean)
    
    if not cours:
        logging.warning("🚫 Aucun cours extrait.")
        return

    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    # --- LOGIQUE DE TEMPS ---
    maintenant = datetime.now()
    annee_actuelle = maintenant.year
    # On autorise les cours qui ont commencé il y a moins de 30 min (marge de sécurité)
    limite_retrait = maintenant - timedelta(minutes=30)

    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 60)

    for c in cours:
        nom = (c.get('nom') or "Inconnu").strip()
        date_str = c.get('date') or ""
        heure_str = c.get('horaire') or ""
        statut = c.get('statut') or "INCONNU"

        # --- FILTRAGE PRÉCIS DATE + HEURE ---
        try:
            # On nettoie l'heure pour le format datetime (18h30 -> 18:30)
            h_clean = heure_str.lower().replace('h', ':')
            date_cours = datetime.strptime(f"{date_str}/{annee_actuelle} {h_clean}", "%d/%m/%Y %H:%M")
            
            # Si le cours est fini depuis plus de 30 min, on le dégage
            if date_cours < limite_retrait:
                continue
        except:
            # Si erreur de parsing, on garde le cours par défaut pour ne pas rater d'alerte
            pass

        # --- TRAITEMENT MÉMOIRE ET ALERTES ---
        if statut == "COMPLET":
            # Le cours est complet ET futur (ou récent) : on l'ajoute à la mémoire
            nouveaux_complets.append(c)
            icon = "🔴"
        else:
            icon = "🟢"
            # Si statut LIBRE, on vérifie s'il était COMPLET dans la mémoire
            etait_complet = any(
                a.get('nom','').strip().lower() == nom.lower() and 
                a.get('date') == date_str and 
                a.get('horaire') == heure_str
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)

        print(f"{icon} {statut:<8} | {date_str:<6} | {heure_str:<10} | {nom}")

    # 5. Envoi des alertes
    if alertes:
        logging.info(f"🚨 {len(alertes)} PLACE(S) LIBÉRÉE(S) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('date')} à {c.get('horaire')}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    
    # 6. Mise à jour mémoire (Écrase avec les cours complets d'aujourd'hui et du futur)
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info(f"🏁 Fin du scan. Mémoire : {len(nouveaux_complets)} cours complets sauvegardés.")

if __name__ == "__main__":
    run_scan()
