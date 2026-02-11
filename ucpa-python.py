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
    options.add_argument("--headless=new")  # Mode headless amélioré
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    # Masquer les signes d'automatisation
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    try:
        # Script pour masquer l'automatisation
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            '''
        })
        
        print(f"🔗 Chargement de la page : {url}")
        driver.get(url)
        
        print(f"📊 Informations initiales :")
        print(f"   - URL actuelle : {driver.current_url}")
        print(f"   - Titre de la page : {driver.title}")
        
        print(f"⏳ Attente du chargement JavaScript (20 secondes)...")
        time.sleep(20)
        
        # --- LOG DU CODE SOURCE HTML COMPLET ---
        page_source = driver.page_source
        print(f"\n🔍 CODE SOURCE HTML ({len(page_source)} caractères) :")
        print("=" * 100)
        print(page_source[:3000])  # Premiers 3000 caractères
        print("=" * 100)
        print(f"... ({len(page_source) - 3000} caractères restants)")
        
        # Vérifier le statut de la page
        if "403" in page_source or "Forbidden" in page_source:
            print("\n❌ ERREUR : Accès bloqué (403 Forbidden)")
            print("💡 Le site détecte le bot et bloque l'accès")
            return ""
        
        if "cloudflare" in page_source.lower():
            print("\n⚠️ ATTENTION : Protection Cloudflare détectée")
        
        # Extraction du texte visible
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        
        # --- LOG DU TEXTE BRUT ---
        print(f"\n📄 TEXTE VISIBLE EXTRAIT ({len(raw_text)} caractères) :")
        print("=" * 100)
        print(raw_text[:3000])  # Afficher les 3000 premiers caractères
        print("=" * 100)
        print(f"... ({len(raw_text) - 3000} caractères restants)\n")
        
        # Recherche de patterns spécifiques pour debug
        print(f"🔎 RECHERCHE DE PATTERNS :")
        patterns_debug = [
            (r"\d{2}\s+lun\.", "Date avec 'lun.'"),
            (r"\d{2}\s+dim\.", "Date avec 'dim.'"),
            (r"Hyrox|Yoga|Pilates|RPM|Bodypump", "Noms de cours"),
            (r"\d{1,2}h\d{2}", "Horaires (format XXhXX)"),
            (r"places? restantes?", "Places restantes"),
            (r"Complet", "Cours complet"),
        ]
        
        for pattern, description in patterns_debug:
            matches = re.findall(pattern, raw_text, re.IGNORECASE)
            if matches:
                print(f"   ✅ {description} : {len(matches)} trouvé(s) - Exemples: {matches[:3]}")
            else:
                print(f"   ❌ {description} : AUCUN")
        
        # --- AUDIT & NETTOYAGE DU TEXTE ---
        print(f"\n🧹 TENTATIVE DE NETTOYAGE AVEC REGEX...")
        match = re.search(r"(\d{2}\s+lun\.)[\s\S]+(\d{2}\s+dim\.)[\s\S]+?(?=\n\s*\n|{{|$)", raw_text)
        
        if match:
            clean_block = match.group(0)
            clean_block = re.sub(r"\{\{.*?\}\}", "", clean_block)
            print(f"✅ Planning détecté via Regex ({len(clean_block)} caractères)")
            print(f"\n📋 PLANNING NETTOYÉ :")
            print("=" * 100)
            print(clean_block[:2000])
            print("=" * 100)
            print(f"... ({len(clean_block) - 2000} caractères restants)\n")
            return clean_block
        else:
            print("⚠️ Format de planning non détecté via Regex")
            truncated = raw_text[:15000]
            print(f"\n📋 TEXTE ENVOYÉ À GEMINI ({len(truncated)} caractères) :")
            print("=" * 100)
            print(truncated[:2000])
            print("=" * 100)
            print(f"... ({len(truncated) - 2000} caractères restants)\n")
            return truncated
    except Exception as e:
        print(f"❌ Erreur Selenium : {e}")
        import traceback
        print(f"📋 TRACEBACK COMPLET :")
        traceback.print_exc()
        return ""
    finally:
        driver.quit()
        print(f"✅ Navigateur fermé")

def analyze_with_gemini(content):
    if not GEMINI_API_KEY: 
        print("⚠️ Clé API Gemini manquante")
        return []
    
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
    
    Réponds UNIQUEMENT avec le tableau JSON, sans texte avant ou après.
    
    Planning à analyser :
    {content}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
        
        # Debug : afficher la réponse brute
        print(f"\n🔍 Réponse Gemini (premiers 500 caractères) :\n{text_resp[:500]}\n")
        
        json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
        if json_match:
            cours = json.loads(json_match.group(0))
            # Valider chaque cours
            cours_valides = []
            for c in cours:
                if all(key in c for key in ['nom', 'jour', 'date', 'horaire', 'places', 'statut']):
                    cours_valides.append(c)
                else:
                    print(f"⚠️ Cours ignoré (données manquantes) : {c}")
            return cours_valides
        else:
            print("⚠️ Aucun JSON trouvé dans la réponse Gemini")
            return []
    except Exception as e:
        print(f"❌ Erreur Gemini : {e}")
        return []

def run_scan():
    print(f"🚀 --- DÉBUT DE L'AUDIT : {datetime.now().strftime('%d/%m/%Y %H:%M')} ---")
    
    clean_text = get_clean_content(URL_CIBLE)
    if not clean_text:
        print("❌ Audit échoué : texte vide.")
        return

    tous_les_cours = analyze_with_gemini(clean_text)
    
    if not tous_les_cours:
        print("⚠️ Aucun cours détecté. Vérifiez la réponse de Gemini ci-dessus.")
        return
    
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
            try: 
                anciens_complets = json.load(f)
            except: 
                anciens_complets = []

    alertes = []
    for actuel in tous_les_cours:
        if actuel['statut'] == "LIBRE":
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
    
    # Mise à jour de la mémoire
    nouveaux_complets = [c for c in tous_les_cours if c['statut'] == "COMPLET"]
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    print(f"\n🏁 Audit terminé. Mémoire mise à jour.")

if __name__ == "__main__":
    run_scan()
