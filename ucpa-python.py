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

# --- CONFIGURATION LOGGING ---
# Sauvegarde tout ce qui se passe dans 'execution.log' + affichage console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- VARIABLES ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def send_whatsapp(message):
    if not GREEN_API_URL or not WHATSAPP_ID:
        logging.warning("⚠️ Pas de configuration WhatsApp.")
        return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        logging.info("✅ Notification WhatsApp envoyée.")
    except Exception as e:
        logging.error(f"❌ Erreur WhatsApp: {e}")

def get_heavy_selenium_content(url):
    logging.info(f"🌐 Lancement du navigateur blindé pour : {url}")
    
    # --- CONFIGURATION SELENIUM "LOURDE" (ANTI-DETECTION) ---
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") # Vital
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    # Masquer les switchs d'automatisation
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    try:
        # Script CDP pour écraser navigator.webdriver (Anti-bot niveau 2)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            '''
        })
        
        driver.get(url)
        
        # Vérification anti-bot basique dans le titre
        logging.info(f"Titre de la page : {driver.title}")
        
        logging.info("⏳ Attente du chargement JS (15s)...")
        time.sleep(15) 
        
        page_source = driver.page_source
        
        # --- DIAGNOSTIC RAPIDE ---
        if "403" in page_source or "Forbidden" in page_source:
            logging.critical("❌ ERREUR : Accès bloqué (403 Forbidden).")
        if "cloudflare" in page_source.lower():
            logging.warning("⚠️ ATTENTION : Protection Cloudflare détectée.")

        # Sauvegarde du code source pour debug via GitHub Artifacts
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(page_source)
            
        # Extraction du texte visible
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text

    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()
        logging.info("Navigateur fermé.")

def clean_and_extract_schedule(raw_text):
    """
    Nettoyage intelligent : On coupe tout ce qui est avant le premier jour de la semaine
    pour ne pas polluer Gemini avec le header du site.
    """
    if not raw_text: return ""
    
    # Cherche 'Lundi 12', 'Mar 13', 'Jeudi' etc.
    pattern = r"(?i)(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\.?\s+\d{0,2}"
    match = re.search(pattern, raw_text)
    
    if match:
        start = match.start()
        # On garde le texte à partir du jour trouvé + 15k caractères max
        clean = raw_text[start : start + 15000]
        logging.info(f"✅ Planning repéré commençant par '{match.group(0)}'.")
        return clean
    else:
        logging.warning("⚠️ Pas de jour détecté explicitement. Envoi du texte brut tronqué.")
        return raw_text[:15000]

def analyze_with_gemini(content):
    if not GEMINI_API_KEY:
        logging.error("⚠️ Clé API Gemini manquante")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse le texte ci-dessous (planning salle de sport).
    Extrais un tableau JSON strict.
    Chaque objet : {{ "nom": "...", "jour": "...", "date": "DD/MM", "horaire": "HHhMM", "statut": "LIBRE" ou "COMPLET", "places": "..." }}
    
    Si tu vois "Complet" ou "0 place", statut = "COMPLET".
    
    Texte :
    {content}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
        
        json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return []
    except Exception as e:
        logging.error(f"❌ Erreur Gemini : {e}")
        return []

def run_scan():
    logging.info("🚀 --- DÉBUT SCAN ---")
    
    # 1. Récupération "Sale" (Heavy Selenium)
    raw = get_heavy_selenium_content(URL_CIBLE)
    if not raw: return

    # 2. Nettoyage léger
    clean = clean_and_extract_schedule(raw)

    # 3. Analyse IA
    cours = analyze_with_gemini(clean)
    
    if not cours:
        logging.warning("Aucun cours trouvé par l'IA.")
        return

    # 4. Traitement & Affichage
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    nouveaux_complets = []
    alertes = []

    print(f"\n{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 50)

    for c in cours:
        # --- SECURISATION ANTICIPÉE DU NONE-TYPE ---
        nom = c.get('nom') or "Inconnu"
        date = c.get('date') or "??"
        heure = c.get('horaire') or "??"
        statut = c.get('statut') or "INCONNU"
        places = c.get('places') or "" # Évite le crash si places est None
        
        icon = "🔴" if statut == "COMPLET" else "🟢"
        print(f"{icon} {statut:<8} | {date:<6} | {heure:<10} | {nom}")

        # Logique alerte
        if statut == "COMPLET":
            nouveaux_complets.append(c)
        elif statut == "LIBRE":
            etait_complet = any(
                a.get('nom') == nom and a.get('date') == date and a.get('horaire') == heure
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)

    # 5. Envoi Alertes
    if alertes:
        logging.info(f"🚨 {len(alertes)} place(s) libérée(s) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('date')} à {c.get('horaire')}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    
    # 6. Sauvegarde
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info("🏁 Fin du scan.")

if __name__ == "__main__":
    run_scan()
