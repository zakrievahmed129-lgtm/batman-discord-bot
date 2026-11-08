# 🦇 Batman - Assistant Discord Personnel Ultime

Un bot Discord couteau suisse moderne hébergé 24h/24 gratuitement sur Render.

## 🌟 Fonctionnalités Exceptionnelles

### 🖱️ Menus Clic-Droit 100% Furtifs (Apps Discord Personnelles)
* **💬 Répondre à ma place (Studio Ghostwriter V3 Anti-IA)** : Lit automatiquement le fil de la discussion (texte, **message vocal** ou **image**), rédige **zéro emoji** et **zéro ton IA** en imitant **ton humour et ton style** avec boutons interactifs : `📋 Copier 1/2/3`, `🎯 + Humour`, `🎭 Mon humour`, `✍️ Guider`, `🔥 Piquant`, `📏 + Court` et `🔄 Autres`.
* **🧠 Résumer avec Batman** : **Écoute les messages vocaux en cachette** (transcription + résumé sans lancer l'audio !), résume les PDF/fichiers, les longs pavés ou rattrape les 25 derniers messages d'une discussion manquée.
* **🎭 Analyser ton & sous-entendus** : Décode l'ironie, les excuses/mythos, l'intérêt caché (même à l'intonation d'un vocal !) + bouton direct pour préparer 3 réponses adaptées.
* **🔍 Analyser l'image (IA)** : Mode furtif qui résout un devoir/exercice pris en photo, lit le texte (OCR) ou explique un mème sans que personne dans le chat ne le voie.
* **📝 Sauvegarder en note** : Enregistre un message ou fichier dans ton carnet personnel en 1 clic.
* **🦇 Profil & Avatar HD** : Clic droit sur un profil pour voir l'âge exact du compte et télécharger son avatar HD.

### 🎮 Mini-Jeux & Sondages Interactifs
* /morpion [adversaire] : Une vraie grille 3x3 jouable avec des boutons directement dans Discord.
* /sondage question + options : Sondage en temps réel avec barres visuelles (🟩🟩⬜ 66%).
* /dice : Lance des dés à N faces.

### 📋 To-Do & Notes Interactives
* /todo : Coche tes tâches d'un clic dans un menu déroulant, modifie-les, ou ajoute-en via une modale interactive.
* /note : Carnet de bord complet avec ajout rapide et suppression interactive.
* /rappel : Minuteur avec alerte automatique en message privé (MP).
* /chrono : Minuteur de travail Pomodoro.

### 🧠 Intelligence Artificielle & Super-Pouvoirs Personnels
* **Analyse & Clonage 100% Automatique** : Aucun paramétrage nécessaire ! Batman apprend ta façon d'écrire automatiquement et lit le fil des discussions.
* **/ia** `question` `[fichier]` `[prive]` : Gemini connecté à **Google Search en direct** + lecture d'Images, Messages Vocaux, PDF et Code (en mode furtif par défaut !).
* **/verifier** `affirmation` : **Détecteur de mytho & Fact-Check Google en direct** en mode furtif, avec preuves et réplique prête à copier.
* **/image** & **/imagine** : Génère des visuels Haute Définition par IA avec choix de formats (1:1, 16:9, 9:16) et régénération.
* **/reformuler** `texte` `style` : Réécrit ou corrige ton message en privé (SMS Discord naturel, Zéro faute, Pro, Clash...).
* **/repartie** `sujet` `[intensite]` : Génère 3 punchlines naturelles en mode 100% furtif.
* **/afk** `[raison]` : Mode absence intelligent.
* **/traduire**, **/meteo**, **/calcul**, **/batman** : Tous tes outils quotidiens accessibles partout (MP, groupes et serveurs).

### 🔄 Statut Rotatif & H24
Le bot alterne automatiquement ses statuts toutes les 5 minutes (Roblox, Gotham, /aide, /todo) et reste éveillé 24h/24 grâce à son serveur web interne !

---

## 🚀 Déploiement Facile (H24 Gratuit sur Render)

1. Crée un nouveau **Web Service** sur [Render.com](https://render.com) en connectant ce dépôt GitHub.
2. Configure les paramètres suivants :
   * **Runtime** : `Python 3`
   * **Build Command** : `pip install -r requirements.txt`
   * **Start Command** : `python main.py`
3. Ajoute tes variables secrètes dans l'onglet **Environment** :
   * `DISCORD_TOKEN` : Ton token de bot Discord
   * `GEMINI_API_KEY` : Ta clé d'API Google AI Studio (gratuite)
   * `PORT` : `10000` (automatique sur Render)
4. Déploie ! Ton bot Batman sera en ligne 24h/24 avec toutes ses commandes synchronisées.

---

## 🔗 Inviter Batman sur ton serveur
1. Sur le [Discord Developer Portal](https://discord.com/developers/applications), va dans **OAuth2 ➔ URL Generator**.
2. Coche uniquement :
   * **Scopes** : `bot` et `applications.commands`
   * **Bot Permissions** : `Administrateur` (ou `Envoyer des messages`, `Voir les anciens messages`, `Intégrer des liens`).
3. Ouvre le lien généré dans ton navigateur et sélectionne ton serveur.
4. Dans l'onglet **Bot**, active la case **Message Content Intent** sous *Privileged Gateway Intents* pour permettre l'apprentissage de ton style en temps réel !
