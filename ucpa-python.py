import os
import json
import time
import re
import requests
import logging
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION LOGGING ---
# Enregistre les logs dans un fichier ET dans la console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# --- VARIABLES D'ENVIRONNEMENT ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GREEN_API_URL = os.getenv('GREEN_API_URL')
WHATSAPP_ID = os.getenv('WHATSAPP_ID')
URL_CIBLE = 'https://www.ucpa.com/sport-station/nantes/fitness'
COURS_CIBLES = os.getenv('COURS_CIBLES', '') # Par défaut vide = tout accepter

def send_whatsapp(message):
    """Envoie une notification WhatsApp via GreenAPI."""
    if not GREEN_API_URL or not WHATSAPP_ID:
        logging.warning("⚠️ Pas de configuration WhatsApp (Variables manquantes).")
        return
    payload = {"chatId": WHATSAPP_ID, "message": message}
    try:
        requests.post(GREEN_API_URL, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
        logging.info("✅ Notification WhatsApp envoyée.")
    except Exception as e:
        logging.error(f"❌ Erreur envoi WhatsApp: {e}")

def get_heavy_selenium_content(url):
    """
    Lance un navigateur, force le scroll et attend le chargement effectif des données JS.
    """
    logging.info(f"🌐 Lancement du navigateur blindé pour : {url}")
    
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled") 
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    try:
        # Masquer navigator.webdriver
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
        
        driver.get(url)
        logging.info("⏳ Page chargée. Début du traitement JS...")

        # 1. SCROLL PROGRESSIF (Crucial pour déclencher le chargement des données)
        # On descend par pas de 500 pixels
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(0, last_height, 500):
            driver.execute_script(f"window.scrollTo(0, {i});")
            time.sleep(0.5) # Petite pause pour laisser le temps au contenu d'apparaître
        
        # Remonter en haut (parfois nécessaire pour voir le début du planning)
        driver.execute_script("window.scrollTo(0, 0);")

        # 2. ATTENTE INTELLIGENTE (Smart Wait)
        # On attend jusqu'à 20 secondes qu'un indice de "vraie donnée" apparaisse.
        # Ici on cherche le mot "restantes" (pour "places restantes") ou un format d'heure "00"
        # OU l'absence des balises moustaches.
        try:
            logging.info("⏳ Attente de l'injection des données dans le tableau...")
            WebDriverWait(driver, 20).until(
                lambda d: "restantes" in d.find_element(By.TAG_NAME, "body").text.lower() or 
                          "complet" in d.find_element(By.TAG_NAME, "body").text.lower()
            )
            logging.info("✅ Données détectées (mots clés 'restantes' ou 'complet' trouvés).")
        except Exception:
            logging.warning("⚠️ Timeout : Les données dynamiques semblent ne pas s'être chargées. On tente quand même l'extraction.")

        # 3. Sauvegarde HTML pour debug
        page_source = driver.page_source
        if "403" in page_source or "Forbidden" in page_source:
            logging.critical("❌ ERREUR : Accès bloqué (403 Forbidden).")
        
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(page_source)
            
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        return raw_text

    except Exception as e:
        logging.error(f"❌ Crash Selenium : {e}")
        return ""
    finally:
        driver.quit()
        logging.info("✅ Navigateur fermé.")
        
def clean_and_extract_schedule(raw_text):
    """
    Nettoyage basé sur la phrase clé indiquée par l'utilisateur.
    Tout ce qui se trouve après cette phrase est considéré comme étant le planning.
    """
    if not raw_text: return ""

    # La phrase exacte que tu as repérée
    phrase_amorce = "Si vous êtes titulaire d'une carte ou de l'abonnement, rendez-vous dans votre espace personnel pour réserver votre séance."

    logging.info(f"🧹 Recherche de la phrase d'amorce dans le texte...")

    clean_text = ""

    # 1. Méthode principale : On cherche la phrase exacte
    if phrase_amorce in raw_text:
        # On coupe le texte en deux et on garde la partie APRES (index [1])
        parts = raw_text.split(phrase_amorce)
        if len(parts) > 1:
            clean_text = parts[1]
            logging.info("✅ Phrase d'amorce trouvée ! Extraction du contenu suivant.")
        else:
            clean_text = raw_text
    else:
        # 2. Méthode de secours (au cas où ils changent un mot dans la phrase)
        # On cherche juste "rendez-vous dans votre espace personnel"
        logging.warning("⚠️ Phrase exacte non trouvée. Essai avec un fragment plus court...")
        fragment_court = "rendez-vous dans votre espace personnel"
        
        if fragment_court in raw_text:
            parts = raw_text.split(fragment_court)
            clean_text = parts[-1]
            logging.info("✅ Fragment court trouvé. Extraction effectuée.")
        else:
            logging.error("❌ Aucune phrase d'amorce trouvée. On envoie le texte brut (risque de bruit).")
            clean_text = raw_text

    # On limite la taille pour Gemini (15 000 caractères suffisent pour une semaine)
    final_text = clean_text[:15000]

    # --- APERÇU POUR DEBUG ---
    logging.info("🔍 --- DÉBUT DU TEXTE ENVOYÉ À L'IA (500 car.) ---")
    # On nettoie les sauts de ligne multiples pour l'affichage log
    preview = re.sub(r'\n+', ' ', final_text[:500])
    logging.info(preview)
    logging.info("---------------------------------------------------")

    return final_text
def analyze_with_gemini(content):
    """Interroge Gemini pour transformer le texte en JSON."""
    if not GEMINI_API_KEY:
        logging.error("⚠️ Clé API Gemini manquante")
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    Analyse ce texte de planning sportif.
    Extrais un tableau JSON strict.
    Chaque objet doit avoir : {{ "nom": "...", "jour": "...", "date": "DD/MM", "horaire": "HHhMM", "statut": "LIBRE" ou "COMPLET", "places": "..." }}
    Règles :
    1. Si tu vois "Complet" ou "0 place", statut = "COMPLET".
    2. Si tu vois "X places restantes", statut = "LIBRE".
    3. Ignore le texte inutile (menus, footer).
    
    Texte :
    {content}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    # --- SYSTÈME DE RETRY (Anti Erreur 429) ---
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            
            # Gestion du Quota dépassé
            if resp.status_code == 429:
                wait_time = (attempt + 1) * 15 # Attente progressive : 15s, 30s...
                logging.warning(f"⚠️ Quota Gemini (429). Pause de {wait_time}s avant nouvel essai...")
                time.sleep(wait_time)
                continue
            
            resp.raise_for_status() # Lève une erreur pour les codes 400, 500...
            
            text_resp = resp.json()['candidates'][0]['content']['parts'][0]['text']
            
            # Extraction du JSON dans la réponse (parfois Gemini met du texte autour)
            json_match = re.search(r'\[.*\]', text_resp, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            else:
                logging.error("⚠️ Pas de JSON trouvé dans la réponse Gemini.")
                return []
                
        except Exception as e:
            logging.error(f"❌ Erreur Gemini (Essai {attempt+1}): {e}")
            time.sleep(5)
            
    return []
# Ajoute cette ligne tout en haut avec les autres variables
COURS_CIBLES = os.getenv('COURS_CIBLES', '') # Par défaut vide = tout accepter

def run_scan():
    logging.info("🚀 --- DÉBUT DE L'AUDIT ---")
    
    # 1. Préparation des filtres
    if COURS_CIBLES:
        # On nettoie la liste : "Hyrox, Yoga" -> ['hyrox', 'yoga']
        mots_cles = [m.strip().lower() for m in COURS_CIBLES.split(',')]
        logging.info(f"🎯 Filtre actif. Je ne cherche que : {mots_cles}")
    else:
        mots_cles = []
        logging.info("📢 Pas de filtre : Je surveille TOUS les cours.")

    # 2. Scraping
    raw = get_heavy_selenium_content(URL_CIBLE)
    if not raw: return

    # 3. Nettoyage
    clean = clean_and_extract_schedule(raw)

    # 4. Analyse IA
    cours = analyze_with_gemini(clean)
    
    if not cours:
        logging.warning("🚫 Aucun cours extrait par l'IA. Fin du scan.")
        return

    # 5. Chargement mémoire
    memo_file = 'memoire_ucpa.json'
    anciens_complets = []
    if os.path.exists(memo_file):
        with open(memo_file, 'r', encoding='utf-8') as f:
            try: anciens_complets = json.load(f)
            except: pass

    nouveaux_complets = []
    alertes = []

    logging.info(f"\n📋 ANALYSE DES COURS :")
    print(f"{'ACTION':<8} | {'STATUT':<8} | {'JOUR':<10} | {'HEURE':<8} | {'COURS'}")
    print("-" * 60)

    for c in cours:
        nom = c.get('nom', 'Inconnu')
        date = c.get('date', '??')
        heure = c.get('horaire', '??')
        statut = c.get('statut', 'INCONNU')
        
        # --- FILTRAGE ---
        # Si une liste de cibles existe, on vérifie si le nom correspond
        if mots_cles:
            is_match = any(mot in nom.lower() for mot in mots_cles)
            if not is_match:
                # On ignore ce cours (on ne l'affiche même pas ou en gris)
                # print(f"⚪ IGNORÉ   | {statut:<8} | {date:<10} | {heure:<8} | {nom}")
                continue 

        # Si on arrive ici, c'est que le cours nous intéresse
        icon = "🔴" if statut == "COMPLET" else "🟢"
        print(f"{icon} SUIVI   | {statut:<8} | {date:<10} | {heure:<8} | {nom}")

        # Logique de détection
        if statut == "COMPLET":
            nouveaux_complets.append(c)
        elif statut == "LIBRE":
            etait_complet = any(
                a.get('nom') == nom and a.get('date') == date and a.get('horaire') == heure
                for a in anciens_complets
            )
            if etait_complet:
                alertes.append(c)

    # 6. Envoi des alertes
    if alertes:
        logging.info(f"🚨 {len(alertes)} PLACE(S) CIBLÉE(S) LIBÉRÉE(S) !")
        for c in alertes:
            msg = f"🚨 LIBRE : {c.get('nom')}\n📅 {c.get('date')} à {c.get('horaire')}\n🔗 {URL_CIBLE}"
            send_whatsapp(msg)
    else:
        logging.info("✅ Aucun changement intéressant détecté.")
    
    # 7. Mise à jour de la mémoire
    # Note : On sauvegarde TOUS les complets détectés (même ceux ignorés) 
    # ou seulement ceux suivis ? Mieux vaut sauvegarder ceux filtrés pour éviter des faux positifs si on change le filtre.
    with open(memo_file, 'w', encoding='utf-8') as f:
        json.dump(nouveaux_complets, f, indent=4, ensure_ascii=False)
    
    logging.info("🏁 Fin du scan.")
