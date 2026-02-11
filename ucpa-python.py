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
# Enregistre les logs dans un fichier ET dans la console
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
    """Lance un navigateur Chrome avec des paramètres anti-détection."""
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
    
    # Masquer les indicateurs d'automatisation
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
        logging.info("⏳ Attente du chargement JS (15s)...")
        time.sleep(15) 
        
        page_source = driver.page_source
        
        # --- DIAGNOSTIC RAPIDE ---
        if "403" in page_source or "Forbidden" in page_source:
            logging.critical("❌ ERREUR : Accès bloqué (403 Forbidden).")
        if "cloudflare" in page_source.lower():
            logging.warning("⚠️ ATTENTION : Protection Cloudflare détectée.")

        # Sauvegarde du HTML pour debug (Artifacts GitHub)
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(page_source)
            
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text

    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()
        logging.info("✅ Navigateur fermé.")

def clean_and_extract_schedule(raw_text):
    """Extrait la partie pertinente du texte pour l'envoyer à Gemini."""
    if not raw_text: return ""
    
    # Cherche le premier jour de la semaine (Lundi XX, Mar XX, etc.)
    pattern = r"(?i)(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\.?\s+\d{0,2}"
    match = re.search(pattern, raw_text)
    
    if match:
        start = match.start()
        # On garde le texte à partir du jour trouvé + 15 000 caractères max
        clean = raw_text[start : start + 15000]
        
        logging.info(f"✅ Planning repéré commençant par '{match.group(0)}'.")
        
        # --- APERÇU POUR DEBUG ---
        logging.info("🔍 --- DÉBUT DU TEXTE ENVOYÉ À L'IA (500 car.) ---")
        logging.info(clean[:500].replace('\n', ' ')) # Affichage compact
        logging.info("---------------------------------------------------")
        
        return clean
    else:
        logging.warning("⚠️ Pas de jour détecté explicitement via Regex.")
        # On renvoie quand même le début du texte au cas où
        return raw_text[:15000]

def analyze_with_gemini(content):
    """Interroge Gemini pour transformer le texte en JSON."""
    if not GEMINI_API_KEY:
        logging.error("⚠️ Clé API Gemini manquante")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse ce texte de planning sportif.
    Extrais un tableau JSON strict.
    Chaque objet doit avoir : {{ "nom": "...", "jour": "...", "date": "DD/MM", "horaire": "HHhMM", "statut": "LIBRE" ou "COMPLET", "places": "..." }}
    Règles :
    1. Si tu vois "Complet" ou "0 place", statut = "COMPLET".
    2. Si tu vois "X places restantes", statut = "LIBRE".
    3. Ignore le texte inutile (menus, footer).
    
    Texte :
    {content}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    # --- SYSTÈME DE RETRY (Anti Erreur 429) ---
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            
            # Gestion du Quota dépassé
            if resp.status_code == 429:
                wait_time = (attempt + 1) * 15 # Attente progressive : 15s, 30s...
                logging.warning(f"⚠️ Quota Gemini (429). Pause de {wait_time}s avant nouvel essai...")
                time.sleep(wait_time)
                continue
            
            resp.raise_for_status() # Lève une erreur pour les codes 400, 500...
            
            text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
            
            # Extraction du JSON dans la réponse (parfois Gemini met du texte autour)
            json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            else:
                logging.error("⚠️ Pas de JSON trouvé dans la réponse Gemini.")
                return []
                
        except Exception as e:
            logging.error(f"❌ Erreur Gemini (Essai {attempt+1}): {e}")
            time.sleep(5)
            
    return []

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT ---")
    
    # 1. Scraping
    raw = get_heavy_selenium_content(URL_CIBLE)
    if not raw: return

    # 2. Nettoyage
    clean = clean_and_extract_schedule(raw)

    # 3. Analyse IA
    cours = analyze_with_gemini(clean)
    
    if not cours:
        logging.warning("🚫 Aucun cours extrait par l'IA. Fin du scan.")
        return

    # 4. Chargement de la mémoire (Anciens cours complets)
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    nouveaux_complets = []
    alertes = []

    logging.info(f"\n📋 {len(cours)} COURS ANALYSÉS :")
    print(f"{'STATUT':<8} | {'DATE':<6} | {'HEURE':<10} | {'COURS'}")
    print("-" * 50)

    for c in cours:
        # Sécurisation des données (éviter NoneType error)
        nom = c.get('nom') or "Inconnu"
        date = c.get('date') or "??"
        heure = c.get('horaire') or "??"
        statut = c.get('statut') or "INCONNU"
        places = c.get('places') or "" # Important pour l'affichage
        
        icon = "🔴" if statut == "COMPLET" else "🟢"
        print(f"{icon} {statut:<8} | {date:<6} | {heure:<10} | {nom}")

        # Logique de détection
        if statut == "COMPLET":
            nouveaux_complets.append(c)
        elif statut == "LIBRE":
            # On vérifie si ce cours précis était complet avant
            etait_complet = any(
                a.get('nom') == nom and a.get('date') == date and a.get('horaire') == heure
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)

    # 5. Envoi des alertes
    if alertes:
        logging.info(f"🚨 {len(alertes)} PLACE(S) LIBÉRÉE(S) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('date')} à {c.get('horaire')}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    else:
        logging.info("✅ Aucun changement 'Complet' -> 'Libre' détecté.")
    
    # 6. Mise à jour de la mémoire
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info("🏁 Fin du scan.")

if __name__ == "__main__":
    run_scan()
