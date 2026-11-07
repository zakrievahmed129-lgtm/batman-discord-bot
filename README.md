# 🦇 Batman - Assistant Discord Personnel Ultime

Un bot Discord couteau suisse moderne hébergé 24h/24 gratuitement sur Render.

## 🌟 Fonctionnalités Exceptionnelles

### 🖱️ Menus Clic-Droit (Apps Discord)
* **💬 Répondre à ma place** : Analyse le message reçu et génère 3 propositions de réponses adaptées à ton style de langage personnel (avec bouton d'envoi en 1 clic !).
* **🎭 Analyser ton & sous-entendus** : Décode les non-dits, le ton émotionnel (passif-agressif, ironique, flirteur...) et donne le meilleur conseil pour réagir.
* **🧠 Résumer avec Batman** : Fais un clic droit sur n'importe quel message pour en obtenir un résumé clair via l'IA !
* **🔍 Analyser l'image (IA)** : Clic droit sur n'importe quel message contenant une image pour en obtenir une analyse détaillée par Gemini Vision !
* **📝 Sauvegarder en note** : Clic droit sur un message pour l'enregistrer instantanément dans ton carnet personnel.
* **🦇 Profil & Avatar HD** : Clic droit sur un membre pour voir sa date de création et télécharger son avatar en haute définition.

### 🎮 Mini-Jeux & Sondages Interactifs
* /morpion [adversaire] : Une vraie grille 3x3 jouable avec des boutons directement dans Discord.
* /sondage question + options : Sondage en temps réel avec barres visuelles (🟩🟩⬜ 66%).
* /dice : Lance des dés à N faces.

### 📋 To-Do & Notes Interactives
* /todo : Coche tes tâches d'un clic dans un menu déroulant, modifie-les, ou ajoute-en via une modale interactive.
* /note : Carnet de bord complet avec ajout rapide et suppression interactive.
* /rappel : Minuteur avec alerte automatique en message privé (MP).
* /chrono : Minuteur de travail Pomodoro.

### 🧠 Intelligence Artificielle, Clone de Style & Conversation
* /ia question [image] : Pose tes questions à Gemini avec mémoire continue du fil de discussion et vision multimodale.
* /ia_memoire : Consulte ce que l'IA a en mémoire sur vos échanges récents.
* /ia_reset : Efface l'historique conversationnel pour repartir à zéro.
* /scanner_mon_style [nombre] : Scanne automatiquement tes messages récents dans le salon pour apprendre ta vraie façon d'écrire sans rien copier-coller !
* /mon_style [preset] [description] : Enregistre ou fais analyser par l'IA tes tics de langage et ta façon de parler pour les réponses automatiques.
* /reponds_pour_moi message [intention] : Génère 3 réponses parfaites (dans ton style, piquante ou diplomate) prêtes à envoyer.
* /reformuler texte style : Réécris n'importe quel texte ou brouillon (Professionnel, Clash sans pitié, Batman Noir, Diplomate, Humoristique...).
* /repartie sujet [intensite] : Génère 3 punchlines et réparties immédiates pour clouer le bec sans vulgarité.
* /afk [raison] : Active ton mode absence ; Batman prévient automatiquement ceux qui te mentionnent et t'accueille à ton retour.
* /image description [style] [format] : Génère une image originale en haute définition via l'IA avec boutons de régénération et choix de ratios (1:1, 16:9, 9:16...).
* /imagine prompt : Raccourci rapide pour générer une illustration artistique par IA.
* /traduire texte + langue : Traduction instantanée ultra-naturelle dans toutes les langues.
* /meteo ville : Météo en direct sans clé d'API.
* /calcul expression : Calculatrice scientifique complète.
* /batman : Citations et punchlines légendaires du Chevalier Noir.

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
   * `PORT` : `8080` (automatique sur Render)
4. Déploie ! Ton bot Batman sera en ligne 24h/24 avec toutes ses commandes synchronisées.
