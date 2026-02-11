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
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        print("⏳ Attente du chargement des scripts UCPA (10s)...")
        time.sleep(10) 
        
        # Récupération du texte visible uniquement pour plus de clarté
        page_text = driver.find_element(By.TAG_NAME, "body").text
        return page_text
    except Exception as e:
        print(f"⚠️ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    print("🤖 Envoi des données à l'IA Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"text": content}]}]
    }
    
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        
        if 'candidates' not in resp_json:
            print(f"❌ Erreur API Gemini (Pas de candidats). Réponse reçue : {resp_json}")
            return []
            
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"💥 Erreur lors de l'analyse Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🚀 --- DÉBUT DU SCAN : {date_log} ---") [cite: 2, 3]

    # 1. Scraping et Nettoyage par REGEX
    raw_text = get_dynamic_content(URL_CIBLE)
    
    # Utilisation de la REGEX pour isoler le planning 
    # On cherche de "lun." jusqu'à "HORAIRES"
    match = re.search(r"(\d{2}\s+lun\.)([\s\S]+?)(?=\s+HORAIRES|$)", raw_text)
    
    if match:
        content_to_analyze = match.group(0)
        print(f"✅ Planning extrait avec succès ({len(content_to_analyze)} caractères).")
    else:
        content_to_analyze = raw_text[:20000] # Fallback si regex échoue
        print("⚠️ Regex non trouvée, envoi du texte brut tronqué.") [cite: 7]

    # 2. Analyse Gemini [cite: 9]
    prompt = f"""Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extraie TOUS les cours : Nom, Jour, Date (JJ/MM), Horaire (HH:mm) et Statut (COMPLET ou LIBRE).
    Ignore les cours passés.
    Réponds UNIQUEMENT en JSON : [{{"nom":"...","jour":"...","date":"...","horaire":"...","statut":"..."}}]""" [cite: 10]

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)

    # 3. Comparaison Mémoire [cite: 11]
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try:
                anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = [] [cite: 12]
    print(f"🔎 Analyse de {len(tous_les_cours)} cours...")
    
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

    # 4. Notifications WhatsApp [cite: 13]
    if alertes:
        for c in alertes:
            msg = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
            print(f"📢 ALERTE : {c['nom']} libéré !")
    else:
        print("😴 Aucune nouvelle place libérée.")

    # 5. Sauvegarde [cite: 14, 15]
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    
    print(f"🏁 Fin du scan. Mémoire mise à jour ({len(nouveaux_complets)} cours complets).")

if __name__ == "__main__":
    run_scan()
