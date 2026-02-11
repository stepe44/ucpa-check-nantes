import os
import json
import time
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# --- CONFIGURATION ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'

def send_whatsapp(message):
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        print(f"✅ Notification WhatsApp envoyée.")
    except Exception as e:
        print(f"❌ Erreur WhatsApp: {e}")

def get_clean_content(url):
    print(f"🌐 Connexion à l'UCPA et audit du texte...")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(15) # On laisse un peu plus de temps pour le rendu
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # --- REGEX PLUS SOUPLE (Insensible à la casse) ---
        match = re.search(r"(?i)(\d{0,2}\s*lun\.)[\s\S]+?(\d{0,2}\s*dim\.)", raw_text)
        
        if match:
            print("🎯 Zone de planning détectée avec succès.")
            clean_block = match.group(0)
            clean_block = re.sub(r"\{\{.*?\}\}", "", clean_block)
            return clean_block
        else:
            print("⚠️ Regex non matchée (format différent). Envoi du texte brut filtré.")
            # On retire au moins les balises mustache pour aider l'IA
            return re.sub(r"\{\{.*?\}\}", "", raw_text[:15000])
    except Exception as e:
        print(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_gemini(content):
    if not GEMINI_API_KEY: return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse ce planning. Extrais chaque cours dans un tableau JSON.
    Chaque objet doit avoir : "nom", "jour", "date", "horaire", "places", "statut".
    Statut doit être 'COMPLET' ou 'LIBRE'.
    Si une information est manquante, mets "N/A" (ne laisse pas de valeur nulle).
    
    Texte : {content}
    """
    
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
        text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except:
        return []

def run_scan():
    print(f"🚀 --- DÉBUT DE L'AUDIT : {datetime.now().strftime('%d/%m/%Y %H:%M')} ---")
    clean_text = get_clean_content(URL_CIBLE)
    if not clean_text: return

    tous_les_cours =
