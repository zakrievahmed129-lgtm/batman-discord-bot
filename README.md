# 🦇 Batman - Bot Discord Personnel & H24

Un bot Discord couteau suisse conçu pour être hébergé gratuitement 24h/24 sur Render.

---

## ⚡ Fonctionnalités

* ⏰ **Rappels intelligents (`/rappel`)** : Reçois des rappels en mention Discord (`10m`, `2h`, `45s`, `1j`).
* 📋 **Gestionnaire de tâches (`/todo_ajouter`, `/todo_liste`, `/todo_terminer`)** : To-do list intégrée.
* 📝 **Prise de notes rapide (`/note_ajouter`, `/note_liste`)** : Sauvegarde instantanée de tes idées.
* 🧠 **Assistant IA (`/ia`)** : Pose une question à l'IA (Gemini 2.5 Flash).
* 🌐 **Serveur Web keep-alive intégré** : Permet à Render de rester éveillé H24 via un ping Uptime.

---

## 🚀 Étape 1 : Tester en local (sur ton PC)

1. Remplis le fichier `.env` :
   ```env
   DISCORD_TOKEN=ton_token_secret
   GEMINI_API_KEY=cle_gemini_optionnelle
   PORT=8080
   ```
2. Lance le bot :
   ```bash
   python main.py
   ```
3. Vérifie sur Discord que le bot passe **En ligne** avec le statut `Regarde /aide | Assistant Perso`.

---

## ☁️ Étape 2 : Déployer H24 sur Render (Gratuit)

### 1. Mettre le code sur GitHub
1. Crée un nouveau dépôt privé ou public sur [GitHub](https://github.com/new).
2. Pousse ton code dans ce dépôt :
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/TON_PSEUDO/TON_DEPOT.git
   git push -u origin main
   ```

### 2. Créer le service sur Render
1. Va sur [Render.com](https://render.com/) et connecte-toi avec ton compte GitHub.
2. Clique sur **New +** > **Web Service**.
3. Sélectionne ton dépôt GitHub du bot.
4. Remplis les champs :
   * **Name** : `batman-discord-bot` (ou le nom de ton choix)
   * **Region** : Frankfurt (EU) ou Oregon
   * **Runtime** : `Python 3`
   * **Build Command** : `pip install -r requirements.txt`
   * **Start Command** : `python main.py`
   * **Instance Type** : `Free`
5. Clique sur **Environment Variables** (Variables d'environnement) et ajoute :
   * `DISCORD_TOKEN` = *(colle la valeur de ton token Discord)*
   * `GEMINI_API_KEY` = *(colle ta clé Gemini si tu en as une)*
   * `PORT` = `8080`
6. Clique sur **Create Web Service**. Render va construire et lancer ton bot !

---

## 🔄 Étape 3 : Empêcher Render de s'endormir (100% H24)

L'offre gratuite de Render s'endort après 15 min d'inactivité Web. Pour l'empêcher :
1. Copie l'URL publique fournie par Render pour ton service (ex: `https://batman-discord-bot.onrender.com`).
2. Va sur [UptimeRobot.com](https://uptimerobot.com/) (gratuit).
3. Crée un moniteur :
   * **Monitor Type** : `HTTP(s)`
   * **Friendly Name** : `Bot Discord Batman`
   * **URL** : `https://batman-discord-bot.onrender.com/health`
   * **Monitoring Interval** : Toutes les `10 minutes` ou `5 minutes`.
4. Sauvegarde : UptimeRobot enverra un ping régulier, ce qui gardera ton bot réveillé **24h/24 et 7j/7 sans interruption** !

