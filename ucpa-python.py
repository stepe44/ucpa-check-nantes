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
URL_CIBLE = 'https://r.jina.ai/https://www.ucpa.com/sport-station/nantes/fitness'

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
    """Charge la page avec Selenium"""
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
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        
        print("⏳ Attente du rendu dynamique (détection de 'dim.')...")
        raw_text = ""
        for i in range(10):
            raw_text = driver.find_element(By.TAG_NAME, "body").text
            if "dim." in raw_text.lower():
                print(f"✅ JavaScript validé : Planning complet détecté (tour {i+1}).")
                return raw_text
            time.sleep(3)
        
        print("⚠️ ERREUR : Le mot 'dim.' n'a pas été trouvé.")
        return raw_text
    except Exception as e:
        print(f"⚠️ Erreur Selenium critique : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    """Appel API Gemini 2.0 Flash"""
    print("🤖 Analyse par l'IA Gemini 2.0 Flash...")
    if not GEMINI_API_KEY:
        print("❌ Clé API manquante.")
        return []

    # Correction du modèle : gemini-2.0-flash
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}, {"text": content}]}]}
    
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        
        if 'candidates' not in resp_json:
            print(f"❌ Erreur API Gemini : {resp_json}")
            return []
            
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        # Nettoyage pour ne garder que le JSON
        clean_json = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if clean_json:
            return json.loads(clean_json.group(0))
        return []
    except Exception as e:
        print(f"💥 Erreur parsing Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🚀 --- DÉBUT DU SCAN : {date_log} ---")

    full_text = get_dynamic_content(URL_CIBLE)
    if not full_text: 
        print("❌ Texte vide, arrêt.")
        return

    # --- NOUVELLE REGEX POUR LE PLANNING ---
    # On cherche du premier "XX lun." jusqu'au dernier "XX dim."
    # Elle ignore les balises {{#items}} en amont et en aval.
    match = re.search(r"(\d{2}\s+lun\.)[\s\S]+(\d{2}\s+dim\.)[\s\S]+?(?=\n\s*\n|{{|$)", full_text)
    
    if match:
        content_to_analyze = match.group(0)
        print("📋 --- TEXTE EXTRAIT POUR GEMINI ---")
        print(content_to_analyze) 
        print("-------------------------------------")
    else:
        print("⚠️ Regex non matchée, envoi d'un échantillon par défaut.")
        content_to_analyze = full_text[:15000]

    prompt = f"""
    Nous sommes le {date_log}. 
    Analyse ce planning UCPA (Nantes). 
    Pour chaque cours, extrait : 
    - nom (ex: "Hyrox", "Pilates")
    - jour (ex: "lundi")
    - date (ex: "09/02")
    - horaire (ex: "07h30 - 08h15")
    - statut (LIBRE ou COMPLET). 
    Note : "X places restantes" signifie LIBRE. "Complet" signifie COMPLET.
    Réponds UNIQUEMENT par un tableau JSON.
    """

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)
    print(f"📊 {len(tous_les_cours)} cours extraits par l'IA.")

    # --- GESTION DE LA MÉMOIRE ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            # On vérifie si ce cours précis était complet lors du scan précédent
            etait_complet = any(
                a['nom'] == actuel['nom'] and 
                a['horaire'] == actuel['horaire'] and 
                (a.get('date') == actuel.get('date') or a.get('jour') == actuel.get('jour'))
                for a in anciens_complets
            )
            if etait_complet: 
                alertes.append(actuel)

    if alertes:
        print(f"🚨 {len(alertes)} NOUVELLE(S) PLACE(S) LIBRE(S) !")
        for c in alertes:
            message = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c.get('date', '')} à {c['horaire']}\n🔗 {URL_CIBLE}"
            send_whatsapp(message)
    else:
        print("😴 Aucune libération de place détectée.")

    # Sauvegarde des cours qui sont COMPLETs maintenant pour le prochain scan
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    
    print(f"🏁 Scan terminé. {len(nouveaux_complets)} cours complets sauvegardés.")

if __name__ == "__main__":
    run_scan()
