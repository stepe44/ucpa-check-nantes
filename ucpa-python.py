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
    """Envoie une notification via Green-API"""
    payload = {"chatId": WHATSAPP_ID, "message": message}
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(GREEN_API_URL, json=payload, headers=headers)
        print(f"✅ WhatsApp Response: {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur WhatsApp: {e}")

def get_dynamic_content(url):
    """Charge la page avec Selenium et affiche le résultat dans les logs"""
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
        
        print("⏳ Attente du rendu JavaScript (10s)...")
        time.sleep(10) 
        
        # Récupération du texte brut
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # --- LOG VISUEL ---
        print("📝 --- APERÇU DU CONTENU RÉCUPÉRÉ ---")
        if raw_text:
            print(raw_text[:800] + "...") 
            print(f"📊 Taille totale : {len(raw_text)} caractères")
        else:
            print("⚠️ Le texte récupéré est vide !")
        print("---------------------------------------")
        
        return raw_text
    except Exception as e:
        print(f"⚠️ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    """Analyse les données via Gemini 1.5 Flash"""
    print("🤖 Analyse par l'IA Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}, {"text": content}]}]
    }
    
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        
        if 'candidates' not in resp_json:
            print(f"❌ Erreur API Gemini : {resp_json}")
            return []
            
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        # Nettoyage du bloc de code JSON
        clean_json = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"💥 Erreur parsing Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🚀 --- DÉBUT DU SCAN : {date_log} ---")

    # 1. Scraping et Nettoyage REGEX
    full_text = get_dynamic_content(URL_CIBLE)
    
    if not full_text:
        print("❌ Abandon : Aucun contenu récupéré.")
        return

    # Isoler le planning avec la REGEX fournie
    match = re.search(r"(\d{2}\s+lun\.)([\s\S]+?)(?=\s+HORAIRES|$)", full_text)
    
    if match:
        content_to_analyze = match.group(0)
        print("✅ REGEX : Bloc planning isolé avec succès.")
        print(f"📝 Extrait envoyé à l'IA : {content_to_analyze[:200]}...")
    else:
        content_to_analyze = full_text[:15000]
        print("⚠️ REGEX : Non trouvée, envoi du texte brut tronqué.")

    # 2. Prompt Gemini
    prompt = f"""Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extraie TOUS les cours : Nom, Jour, Date (JJ/MM), Horaire (HH:mm) et Statut (COMPLET ou LIBRE).
    Ignore les cours passés.
    Réponds UNIQUEMENT en JSON : [{{"nom":"...","jour":"...","date":"...","horaire":"...","statut":"..."}}]"""

    # 3. Analyse
    tous_les_cours = get_gemini_data(prompt, content_to_analyze)

    # 4. Comparaison Mémoire
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try:
                anciens_complets = json.load(f)
            except:
                anciens_complets = []

    alertes = []
    print(f"🔎 Analyse de {len(tous_les_cours)} cours détectés...")
    
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

    # 5. Notifications
    if alertes:
        for c in alertes:
            message = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(message)
            print(f"📢 ALERTE : {c['nom']} {c['date']} {c['horaire']}")
    else:
        print("😴 Aucune nouvelle place disponible.")

    # 6. Sauvegarde
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    
    print(f"🏁 Fin du scan. Mémoire : {len(nouveaux_complets)} cours complets sauvegardés.")

if __name__ == "__main__":
    run_scan()
