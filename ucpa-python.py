import os
import json
import time
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
    """Envoie une notification via Green-API"""
    payload = {
        "chatId": WHATSAPP_ID,
        "message": message
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(GREEN_API_URL, json=payload, headers=headers)
        print(f"WhatsApp Response: {response.status_code}")
    except Exception as e:
        print(f"Erreur WhatsApp: {e}")

def get_dynamic_content(url):
    """Charge la page avec Selenium (Headless Chrome) avec gestion de robustesse"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Ajout d'un User-Agent pour éviter le blocage "bot"
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        # On attend 30 secondes que le corps de la page soit présent [cite: 5]
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Pause supplémentaire pour laisser le JavaScript charger le planning [cite: 3]
        time.sleep(10) 
        
        return driver.page_source
    except Exception as e:
        print(f"⚠️ Erreur Selenium (Timeout possible) : {e}")
        return driver.page_source # On renvoie quand même le contenu partiel pour Gemini
    finally:
        driver.quit()

def get_gemini_data(prompt, html_content):
    """Analyse le HTML via Gemini 1.5 Flash"""
    # Utilisation de la version Flash pour la rapidité et le coût [cite: 20]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"text": html_content}]}]
    }
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        # Nettoyage du balisage Markdown JSON [cite: 22]
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Erreur Gemini: {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M") [cite: 2]
    print(f"🕒 Lancement du scan haute précision : {date_log}") [cite: 3]

    # 1. Scraping Selenium
    html_brut = get_dynamic_content(URL_CIBLE)

    # 2. Analyse Gemini [cite: 9]
    prompt = f"""Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extraie TOUS les cours de fitness : Nom, Jour, Date (JJ/MM), Horaire (HH:mm) et Statut (COMPLET ou LIBRE).
    Ignore les cours passés. [cite: 10]
    Réponds UNIQUEMENT en JSON : [{{"nom":"...","jour":"...","date":"...","horaire":"...","statut":"..."}}]"""

    tous_les_cours = get_gemini_data(prompt, html_brut)

    # 3. Comparaison Mémoire [cite: 11]
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try:
                anciens_complets = json.load(f)
            except:
                anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            # Si libre, on vérifie s'il était complet avant [cite: 12]
            etait_complet = any(
                a['nom'] == actuel['nom'] and 
                a['horaire'] == actuel['horaire'] and 
                a['date'] == actuel['date'] 
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(actuel)

    # 4. Envoi des alertes WhatsApp [cite: 13]
    if alertes:
        for c in alertes:
            message = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(message)
            print(f"📢 ALERTE : {c['nom']} libéré !")

    # 5. Sauvegarde de la nouvelle mémoire [cite: 14, 15]
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    
    print(f"🔎 Scan terminé : {len(tous_les_cours)} cours analysés.")

if __name__ == "__main__":
    run_scan()
