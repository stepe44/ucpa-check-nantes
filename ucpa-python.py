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
    """Envoie une alerte via Green-API"""
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"✅ Notification WhatsApp envoyée.")
    except Exception as e:
        print(f"❌ Erreur WhatsApp: {e}")

def get_dynamic_content(url):
    """Récupère le contenu de la page avec Selenium"""
    print(f"🌐 Connexion à l'UCPA...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(12) # Temps nécessaire pour le rendu des cours
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text if len(raw_text) > 500 else ""
    except Exception as e:
        print(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def get_gemini_data(prompt, content):
    """Analyse le texte brut avec Gemini 2.0 Flash"""
    if not GEMINI_API_KEY: return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}, {"text": content}]}]}
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        raw_ai_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\[.*\]', raw_ai_text, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception as e:
        print(f"💥 Erreur Gemini : {e}")
        return []

def run_scan():
    print(f"🚀 --- SCAN UCPA : {datetime.now().strftime('%d/%m/%Y %H:%M')} ---")
    
    full_text = get_dynamic_content(URL_CIBLE)
    if not full_text:
        print("❌ Impossible de lire la page (bloqué ou vide).")
        return

    # Isoler la zone du planning pour l'IA
    match = re.search(r"(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.)[\s\S]+", full_text)
    content_to_analyze = match.group(0) if match else full_text[:15000]

    prompt = """
    Analyse ce planning de sport. Extrais TOUS les cours dans un tableau JSON.
    Chaque objet JSON doit avoir : 
    - "nom" (ex: Body Pump)
    - "jour" (ex: lundi)
    - "date" (format DD/MM)
    - "horaire" (ex: 12:15 - 13:00)
    - "places" (ex: 'Complet' ou 'X places restantes')
    - "statut" ('COMPLET' ou 'LIBRE')
    Réponds UNIQUEMENT avec le JSON.
    """

    tous_les_cours = get_gemini_data(prompt, content_to_analyze)
    
    # --- LOG SIMPLIFIÉ ---
    print(f"\n📋 ÉTAT DU PLANNING :")
    print(f"{'STATUT':<8} | {'JOUR':<10} | {'HEURE':<15} | {'COURS':<20} | {'PLACES'}")
    print("-" * 75)
    for c in tous_les_cours:
        icon = "🔴" if c['statut'] == "COMPLET" else "🟢"
        print(f"{icon} {c['statut']:<6} | {c['jour']:<10} | {c['horaire']:<15} | {c['nom']:<20} | {c['places']}")

    # --- COMPARAISON MÉMOIRE ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel['statut'] == "LIBRE":
            # Vérifier si ce cours était noté COMPLET au scan précédent
            deja_complet = any(
                a['nom'] == actuel['nom'] and 
                a['horaire'] == actuel['horaire'] and 
                a['date'] == actuel['date'] 
                for a in anciens_complets
            )
            if deja_complet:
                alertes.append(actuel)

    if alertes:
        print(f"\n🚨 {len(alertes)} PLACE(S) LIBÉRÉE(S) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🎟 {c['places']}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    else:
        print("\n😴 Aucune nouvelle place disponible.")

    # --- SAUVEGARDE ---
    nouveaux_complets = [c for c in tous_les_cours if c['statut'] == "COMPLET"]
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    print(f"💾 Mémoire mise à jour ({len(nouveaux_complets)} cours complets).")

if __name__ == "__main__":
    run_scan()
