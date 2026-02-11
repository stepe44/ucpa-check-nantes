import os
import json
import time
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
# On attaque le site DIRECTEMENT sans passer par Jina
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def send_whatsapp(message):
    payload = {"chatId": WHATSAPP_ID, "message": message}
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(GREEN_API_URL, json=payload, headers=headers)
        print(f"✅ WhatsApp Response: {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur WhatsApp: {e}")

def get_dynamic_content(url):
    print(f"🌐 Ouverture directe de la page : {url}")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Ajout de flags pour éviter la détection "Bot"
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        
        # On attend qu'un élément du planning soit visible
        print("⏳ Attente du chargement des cours...")
        time.sleep(10) # Pause de sécurité pour le rendu JS
        
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # LOG COMPLET pour débugger sur GitHub
        print("\n" + "="*50)
        print("📝 RETOUR COMPLET DU SCRAPING :")
        print(raw_text)
        print("="*50 + "\n")
        
        return raw_text
    except Exception as e:
        print(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    print("🤖 Analyse par l'IA Gemini...")
    if not GEMINI_API_KEY: return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}, {"text": content}]}]}
    
    try:
        resp = requests.post(url, json=payload)
        raw_ai_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\[.*\]', raw_ai_text, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception as e:
        print(f"💥 Erreur Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🚀 --- SCAN DU {date_log} ---")

    full_text = get_dynamic_content(URL_CIBLE)
    if not full_text or "403" in full_text:
        print("❌ Accès bloqué ou contenu vide.")
        return

    # Regex plus souple pour le texte brut de l'UCPA
    match = re.search(r"(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)[\s\S]+(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)", full_text)
    content_to_analyze = match.group(0) if match else full_text[:20000]

    prompt = f"""
    Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extraie tous les cours en JSON (nom, jour, date, horaire, statut).
    Statut est 'LIBRE' si il y a des places restantes, 'COMPLET' sinon.
    Réponds uniquement en JSON.
    """

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)
    print(f"📊 {len(tous_les_cours)} cours extraits.")

    # --- LOGIQUE DE MÉMOIRE (Identique à avant) ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            etait_complet = any(a['nom'] == actuel['nom'] and a['horaire'] == actuel['horaire'] and a['date'] == actuel['date'] for a in anciens_complets)
            if etait_complet: alertes.append(actuel)

    if alertes:
        for c in alertes:
            msg = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)

    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)

if __name__ == "__main__":
    run_scan()
