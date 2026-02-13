🏊‍♂️ UCPA Check Nantes - Alerte Créneaux Libres

Ce projet est né d'un besoin simple : ne plus rater une place pour un cours à l'UCPA Nantes. Il s'agit de mon premier script réalisé avec une approche "no-code" assistée par l'IA (Gemini), permettant de transformer une tâche répétitive en un automatisme efficace.

🎯 Objectif du projet

Le script surveille en temps réel la page des cours de l'UCPA Nantes. Dès qu'un cours qui était affiché comme "Complet" redevient disponible (suite à un désistement par exemple), le script envoie immédiatement une notification via WhatsApp.

Fonctions principales :

🔍 Webscraping : Analyse automatique de la page des cours UCPA Nantes.

💾 Persistance : Mémorisation de l'état des cours pour identifier les changements.

🔄 Automatisation : Exécution récurrente via une tâche CRON.

📱 Alertes : Notification push via WhatsApp dès qu'une place se libère email ou notification push sur mobile via le service https://ntfy.sh/

🛠️ Fonctionnement Technique

Analyse (Scraping) : Le script récupère le contenu HTML de la page de réservation.

Comparaison d'état : - Il extrait la liste des cours et leur statut (disponible/complet).

Il compare cette liste avec la "dernière photo" prise lors du passage précédent.

Logique de Notification : - SI (Cours X était Complet) ET (Cours X est maintenant Disponible)

ALORS -> Envoi du message WhatsApp.

🚀 Installation et Configuration

1. Pré-requis

Un environnement Python (ou l'outil de script utilisé).

Un accès à un terminal pour configurer le CRON.

Une clé API pour les notifications (ex: CallMeBot pour WhatsApp ou Twilio)

🏋️ UCPA Fitness Spotter - NantesCe bot Python surveille en temps réel les disponibilités des cours de fitness à l'UCPA Sport Station Nantes. Il permet de ne plus rater de places sur les cours très prisés (Yoga, Cross Training, etc.) en envoyant des notifications instantanées dès qu'une place se libère.🌟 Points FortsAnti-Spam Intelligent : Le bot mémorise l'état des cours (via memoire_ucpa.json) et ne déclenche une alerte que si un cours passe du statut "Complet" à "Libre".Multi-Canaux : Notifications via WhatsApp (Green API), Email (SMTP) et SMS (Free Mobile).Filtrage Précis : Surveillez uniquement les disciplines qui vous intéressent via des mots-clés.Reporting Console : Affiche un tableau élégant du planning actuel lors de chaque exécution.🛠 Configuration (Variables d'Environnement)Le script utilise des variables d'environnement pour sa configuration. Vous pouvez les définir dans votre système ou via un fichier .env.📱 NotificationsVariableDescriptionGREEN_API_URLEndpoint Green API pour WhatsAppWHATSAPP_CHAT_IDIdentifiant de la conversation WhatsAppEMAIL_SENDERAdresse Gmail utilisée pour l'envoiEMAIL_PASSWORDMot de passe d'application GmailEMAIL_RECEIVERDestinataires (séparés par des virgules)FREE_SMS_USERIdentifiant API SMS Free MobileFREE_SMS_PASSClé API SMS Free Mobile⚙️ Paramètres du ScanVariableDescriptionCOURS_SURVEILLESListe de mots-clés (ex: yoga, cardio, boxing)🚀 Installation1. Cloner le dépôtgit clone [https://github.com/votre-username/ucpa-fitness-bot.git](https://github.com/votre-username/ucpa-fitness-bot.git)
cd ucpa-fitness-bot
2. Installer les dépendancespip install -r requirements.txt
3. Installer Google ChromeLe script utilise Selenium en mode headless. Assurez-vous que Google Chrome est installé sur votre machine/serveur.💻 UtilisationPour lancer un scan manuellement :python ucpa-python.py
Exemple de sortie console :🔍 Démarrage du scan sur : [https://www.ucpa.com/](https://www.ucpa.com/)...
📊 12 cours détectés :
------------------------------------------------------------
STATUT     | DATE     | HEURE    | COURS               
------------------------------------------------------------
2 places   | 14/10    | 18h30    | YOGA DYNAMIQUE      
COMPLET    | 14/10    | 19h30    | CROSS TRAINING      
------------------------------------------------------------
🚀 ALERTE : Une place s'est libérée pour YOGA DYNAMIQUE !
💾 Mémoire mise à jour (5 cours complets sauvegardés).
🤖 AutomatisationIl est recommandé d'exécuter ce script via une tâche Cron (Linux) ou via GitHub Actions.Exemple de Cron (toutes les 10 minutes) :*/10 * * * * /usr/bin/python3 /path/to/ucpa-python.py >> /var/log/ucpa_bot.log 2>&1

⚠️ AvertissementCe projet est destiné à un usage personnel. Veillez à ne pas surcharger les serveurs de l'UCPA avec des fréquences de scan trop élevées (un intervalle de 10-15 minutes est raisonnable).Projet non-officiel sans lien avec l'UCPA.


C'est la preuve qu'avec les bons outils IA, on peut passer de l'idée au prototype fonctionnel sans être un expert en développement.

Note : Ce script est destiné à un usage personnel et doit respecter les conditions d'utilisation du site de l'UCPA.
