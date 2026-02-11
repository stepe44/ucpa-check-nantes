import os
import json
import time
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
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
    """Charge la page avec Selenium (Headless Chrome)"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # Utilisation du driver par défaut de l'image Ubuntu de GitHub Actions
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 20)
        # On attend le chargement effectif du planning
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#activity_color, .class")))
        time.sleep(2) 
        return driver.page_source
    finally:
        driver.quit()

def get_gemini_data(prompt, html_content):
    """Analyse le HTML via Gemini"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"text": html_content}]}]
    }
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        # Nettoyage Markdown
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Erreur Gemini: {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🕒 Lancement du scan : {date_log}")

    # 1. Scraping
    html_brut = get_dynamic_content(URL_CIBLE)

    # 2. Analyse Gemini
    prompt = f"""Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extraie TOUS les cours : Nom, Jour, Date (JJ/MM), Horaire (HH:mm) et Statut (COMPLET ou LIBRE).
    Ignore les cours passés.
    Réponds UNIQUEMENT en JSON : [{{"nom":"...","jour":"...","date":"...","horaire":"...","statut":"..."}}]"""

    tous_les_cours = get_gemini_data(prompt, html_brut)

    # 3. Comparaison Mémoire
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            anciens_complets = json.load(f)

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            etait_complet = any(
                a['nom'] == actuel['nom'] and 
                a['horaire'] == actuel['horaire'] and 
                a['date'] == actuel['date'] 
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(actuel)

    # 4. Alertes
    if alertes:
        for c in alertes:
            message = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(message)
            print(f"📢 ALERTE envoyée pour : {c['nom']}")

    # 5. Sauvegarde
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    print(f"✅ Scan terminé. {len(nouveaux_complets)} cours complets en mémoire.")

if __name__ == "__main__":
    run_scan()
