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
        time.sleep(12) # Attente du rendu JS
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # --- AUDIT & NETTOYAGE DU TEXTE ---
        # 1. On cherche le début du planning (ex: 09 lun.) et la fin (15 dim. + les cours suivants)
        match = re.search(r"(\d{2}\s+lun\.)[\s\S]+(\d{2}\s+dim\.)[\s\S]+?(?=\n\s*\n|{{|$)", raw_text)
        
        if match:
            clean_block = match.group(0)
            # 2. On supprime les balises Mustache résiduelles pour aider l'IA
            clean_block = re.sub(r"\{\{.*?\}\}", "", clean_block)
            return clean_block
        else:
            print("⚠️ Format de planning non détecté via Regex, envoi du texte brut élagué.")
            return raw_text[:15000]
    except Exception as e:
        print(f"❌ Erreur Selenium : {e}")
        return ""
    finally:
        driver.quit()

def analyze_with_gemini(content):
    if not GEMINI_API_KEY: return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse ce planning de sport. Ignore les balises de code.
    Extrais chaque cours dans un tableau JSON.
    Chaque objet doit avoir :
    - "nom" : nom du cours (ex: Hyrox, Yoga)
    - "jour" : le jour (lundi, mardi, etc.)
    - "date" : la date au format DD/MM
    - "horaire" : format HHhMM (ex: 07h30 - 08h15)
    - "places" : le texte exact (ex: '6 places restantes' ou 'Complet')
    - "statut" : 'COMPLET' si c'est marqué 'Complet', sinon 'LIBRE'.
    
    Planning à analyser :
    {content}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception:
        return []

def run_scan():
    print(f"🚀 --- DÉBUT DE L'AUDIT : {datetime.now().strftime('%d/%m/%Y %H:%M')} ---")
    
    clean_text = get_clean_content(URL_CIBLE)
    if not clean_text:
        print("❌ Audit échoué : texte vide.")
        return

    tous_les_cours = analyze_with_gemini(clean_text)
    
    # --- AFFICHAGE LOGS SIMPLIFIÉS ---
    print(f"\n📋 LISTE DES COURS :")
    print(f"{'STATUT':<8} | {'DATE':<6} | {'HEURE':<15} | {'COURS':<20} | {'PLACES'}")
    print("-" * 75)
    
    for c in tous_les_cours:
        icon = "🔴" if c['statut'] == "COMPLET" else "🟢"
        print(f"{icon} {c['statut']:<6} | {c['date']:<6} | {c['horaire']:<15} | {c['nom']:<20} | {c['places']}")

    # --- GESTION MÉMOIRE ---
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel['statut'] == "LIBRE":
            # On cherche si ce cours précis (nom + date + heure) était complet avant
            etait_complet = any(
                a['nom'] == actuel['nom'] and 
                a['date'] == actuel['date'] and 
                a['horaire'] == actuel['horaire'] 
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(actuel)

    if alertes:
        print(f"\n🚨 {len(alertes)} PLACE(S) LIBÉRÉE(S) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c['nom']}\n📅 {c['jour']} {c['date']} à {c['horaire']}\n🎟 {c['places']}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    
    # Mise à jour de la mémoire avec les cours actuellement complets
    nouveaux_complets = [c for c in tous_les_cours if c['statut'] == "COMPLET"]
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    print(f"\n🏁 Audit terminé. Mémoire mise à jour.")

if __name__ == "__main__":
    run_scan()
