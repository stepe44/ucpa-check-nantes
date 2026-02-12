🏊‍♂️ UCPA Check Nantes - Alerte Créneaux Libres

Ce projet est né d'un besoin simple : ne plus rater une place pour un cours à l'UCPA Nantes. Il s'agit de mon premier script réalisé avec une approche "no-code" assistée par l'IA (Gemini), permettant de transformer une tâche répétitive en un automatisme efficace.

🎯 Objectif du projet

Le script surveille en temps réel la page des cours de l'UCPA Nantes. Dès qu'un cours qui était affiché comme "Complet" redevient disponible (suite à un désistement par exemple), le script envoie immédiatement une notification via WhatsApp.

Fonctions principales :

🔍 Webscraping : Analyse automatique de la page des cours UCPA Nantes.

💾 Persistance : Mémorisation de l'état des cours pour identifier les changements.

🔄 Automatisation : Exécution récurrente via une tâche CRON.

📱 Alertes : Notification push via WhatsApp dès qu'une place se libère.

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

Une clé API pour les notifications (ex: CallMeBot pour WhatsApp ou Twilio).

2. Installation

# Cloner le projet
git clone [https://github.com/votre-utilisateur/ucpa-check-nantes.git](https://github.com/votre-utilisateur/ucpa-check-nantes.git)

# Installer les librairies nécessaires
pip install -r requirements.txt


3. Automatisation avec CRON

Pour vérifier les places toutes les 10 minutes, ajoutez cette ligne à votre table CRON (crontab -e) :

*/10 * * * * /usr/bin/python3 /votre/chemin/ucpa_check.py >> /votre/chemin/log_ucpa.txt 2>&1


📋 Roadmap / Améliorations futures

[ ] Ajouter la possibilité de choisir des créneaux horaires spécifiques.

[ ] Gérer plusieurs centres UCPA.

[ ] Créer une mini interface web pour visualiser l'historique des disponibilités.

🤖 Crédits

Réalisé avec l'aide de Gemini pour la logique de script et la structuration des données.

C'est la preuve qu'avec les bons outils IA, on peut passer de l'idée au prototype fonctionnel sans être un expert en développement.

Note : Ce script est destiné à un usage personnel et doit respecter les conditions d'utilisation du site de l'UCPA.
