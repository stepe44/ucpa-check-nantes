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
    print(f"🌐 Ouverture de la page : {url}")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))) [cite: 3]
        
        # --- EXÉCUTION DE JAVASCRIPT PERSONNALISÉ ---
        # Exemple : Forcer le défilement vers le bas pour déclencher le lazy-loading
        print("⚙️ Exécution du code JS personnalisé...")
        custom_js = """
        window.scrollTo(0, document.body.scrollHeight);
        console.log('JS personnalisé exécuté : Page scrollée');
        """
        driver.execute_script(custom_js)
        
        # Attente de la détection du planning complet (dimanche)
        js_succes = False
        raw_text = ""
        for i in range(10):
            raw_text = driver.find_element(By.TAG_NAME, "body").text
            if "dim." in raw_text.lower():
                print(f"✅ Planning chargé : 'dim.' trouvé au tour {i+1}.")
                js_succes = True
                break
            time.sleep(3)
        
        if not js_succes:
            send_whatsapp("⚠️ UCPA-ALERT : Échec du chargement dynamique (mot 'dim.' absent).")
        
        return raw_text
    except Exception as e:
        print(f"⚠️ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}" [cite: 20]
    payload = {"contents": [{"parts": [{"text": prompt}, {"text": content}]}]} [cite: 21]
    try:
        resp = requests.post(url, json=payload) [cite: 22]
        resp_json = resp.json()
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text'] [cite: 22]
        clean_json = raw_text.replace("```json", "").replace("```", "").strip() [cite: 22]
        return json.loads(clean_json) [cite: 23]
    except Exception as e:
        print(f"❌ Erreur Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now() [cite: 2]
    date_log = maintenant.strftime("%d/%m/%Y %H:%M") [cite: 2]
    print(f"🚀 --- DÉBUT DU SCAN : {date_log} ---") [cite: 3]

    full_text = get_dynamic_content(URL_CIBLE)
    if not full_text: return

    # Nettoyage par Regex 
    match = re.search(r"(\d{2}\s+lun\.)([\s\S]+?)(?=\s+HORAIRES|$)", full_text) [cite: 18]
    content_to_analyze = match.group(0) if match else full_text[:15000]

    prompt = f"Analyse ce planning UCPA du {date_log}. Extrais les cours en JSON : nom, jour, date, horaire, statut (COMPLET ou LIBRE)." [cite: 8, 9, 10]

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)

    # Gestion de la mémoire et alertes [cite: 11, 12, 13]
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            etait_complet = any(a['nom'] == actuel['nom'] and a['horaire'] == actuel['horaire'] and a['date'] == actuel['date'] for a in anciens_complets) [cite: 12]
            if etait_complet: alertes.append(actuel) [cite: 12]

    if alertes:
        for c in alertes:
            msg = f"🚨 PLACE LIBRE : {c['nom']} le {c['jour']} {c['date']} à {c['horaire']}" [cite: 13]
            send_whatsapp(msg) [cite: 13]

    # Sauvegarde [cite: 14, 15]
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"] [cite: 14]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f) [cite: 15]
    
    print(f"🏁 Scan terminé ({len(nouveaux_complets)} cours complets).")

if __name__ == "__main__":
    run_scan()
