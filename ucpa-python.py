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
# URL Jina pour un formatage Markdown propre via Selenium
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
    """Charge la page avec Selenium pour interpréter le JS"""
    print(f"🌐 Ouverture de la page (Selenium) : {url}")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        # Attente que le corps de la page soit présent
        wait = WebDriverWait(driver, 30)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Petit délai supplémentaire pour laisser le JS de Jina/UCPA finir le rendu
        time.sleep(5)
        
        # Récupération du texte brut interprété par Selenium
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # --- LOG COMPLET DU SCRAPING (Pour debug GitHub) ---
        print("\n" + "="*50)
        print("📝 RETOUR COMPLET DU SCRAPING (BODY TEXT) :")
        print(raw_text)
        print("="*50 + "\n")
        
        return raw_text
    except Exception as e:
        print(f"⚠️ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    """Appel API Gemini 2.0 Flash"""
    print("🤖 Analyse par l'IA Gemini 2.0 Flash...")
    if not GEMINI_API_KEY:
        print("❌ Clé API manquante.")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}, {"text": content}]}]}
    
    try:
        resp = requests.post(url, json=payload)
        resp_json = resp.json()
        
        if 'candidates' not in resp_json:
            print(f"❌ Erreur API Gemini : {resp_json}")
            return []
            
        raw_ai_text = resp_json['candidates'][0]['content']['parts'][0]['text']
        # Nettoyage pour extraire le bloc JSON [ ... ]
        json_match = re.search(r'\[.*\]', raw_ai_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return []
    except Exception as e:
        print(f"💥 Erreur parsing Gemini : {e}")
        return []

def run_scan():
    maintenant = datetime.now()
    date_log = maintenant.strftime("%d/%m/%Y %H:%M")
    print(f"🚀 --- DÉBUT DU SCAN : {date_log} ---")

    full_text = get_dynamic_content(URL_CIBLE)
    if not full_text or len(full_text) < 500:
        print("❌ Contenu insuffisant récupéré. Vérifie les logs Selenium.")
        return

    # --- REGEX POUR TROUVER LE PLANNING ---
    # On cherche du premier "lun." jusqu'au dernier "dim." de la semaine
    # Cette regex est robuste face aux balises {{ }} présentes dans ton extraction
    match = re.search(r"(\d{2}\s+lun\.)[\s\S]+(\d{2}\s+dim\.)", full_text)
    
    if match:
        content_to_analyze = match.group(0)
        print(f"🎯 Planning isolé (de {match.group(1)} à {match.group(2)})")
    else:
        print("⚠️ Regex non matchée, envoi d'un large extrait par sécurité.")
        content_to_analyze = full_text[:15000]

    prompt = f"""
    Nous sommes le {date_log}. Analyse ce planning UCPA.
    Extrais les cours en JSON : nom, jour, date, horaire, statut (COMPLET ou LIBRE).
    Règles :
    - "X places restantes" ou "[RÉSERVER]" -> statut: "LIBRE"
    - "Complet" -> statut: "COMPLET"
    - "date" au format DD/MM
    Réponds UNIQUEMENT en JSON (liste d'objets).
    """

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)
    print(f"📊 {len(tous_les_cours)} cours extraits.")

    # --- MÉMOIRE ET COMPARAISON ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel.get('statut') == "LIBRE":
            # On vérifie si ce cours était noté complet auparavant
            etait_complet = any(
                a['nom'] == actuel['nom'] and 
                a['horaire'] == actuel['horaire'] and 
                a['date'] == actuel['date'] 
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(actuel)

    if alertes:
        for c in alertes:
            msg = f"🚨 PLACE LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🔗 https://www.ucpa.com/sport-station/nantes/fitness"
            send_whatsapp(msg)
            print(f"📢 Notification envoyée pour {c['nom']}")

    # Sauvegarde du nouvel état "Complet"
    nouveaux_complets = [c for c in tous_les_cours if c.get('statut') == "COMPLET"]
    with open(memo_file, 'w') as f:
        json.dump(nouveaux_complets, f)
    
    print(f"🏁 Fin du scan. {len(nouveaux_complets)} cours complets en mémoire.")

if __name__ == "__main__":
    run_scan()
