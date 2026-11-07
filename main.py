import os
import json
import asyncio
import re
import random
import math
import io
import urllib.parse
from datetime import datetime, timezone
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ─────────────────────────── CONFIG ───────────────────────────
load_dotenv()

TOKEN      = os.getenv("DISCORD_TOKEN")
PORT       = int(os.getenv("PORT", "8080"))

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
NOTES_FILE  = os.path.join(DATA_DIR, "notes.json")
TODOS_FILE  = os.path.join(DATA_DIR, "todos.json")

def load_json(fp):
    if os.path.exists(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(fp, data):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
start_time = datetime.now(timezone.utc)

# ──────────────────── KEEP-ALIVE WEB SERVER ───────────────────
async def handle_root(req):
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    return web.json_response({
        "status": "online", "bot": str(bot.user),
        "uptime_seconds": uptime,
        "message": "🦇 Batman Discord Bot — actif H24 !"
    })

async def handle_health(req):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"🌐 Keep-alive server on port {PORT}", flush=True)

# ─────────────────── ROTATION DU STATUT H24 ───────────────────
PRESENCE_ACTIVITIES = [
    (discord.ActivityType.playing, "Sauver Gotham City 🦇"),
    (discord.ActivityType.playing, "Roblox (en cachette) 🤫🎮"),
    (discord.ActivityType.watching, "tes tâches dans /todo 📋"),
    (discord.ActivityType.listening, "les murmures de Gotham 🌙"),
    (discord.ActivityType.watching, "/aide | Ton assistant ⚡")
]

@tasks.loop(minutes=5)
async def rotate_presence():
    act_type, name = random.choice(PRESENCE_ACTIVITIES)
    await bot.change_presence(activity=discord.Activity(type=act_type, name=name))

@rotate_presence.before_loop
async def before_rotate():
    await bot.wait_until_ready()

# ─────────────────────── ON READY ─────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Connected as {bot.user} ({bot.user.id})", flush=True)
    try:
        synced = await bot.tree.sync()
        print(f"⚡ {len(synced)} interactions synced (slash + context menus).", flush=True)
    except Exception as e:
        print(f"⚠️ Sync error: {e}", flush=True)
    
    if not rotate_presence.is_running():
        rotate_presence.start()

# ══════════════════════════════════════════════════════════════
#  DÉCORATIONS COMMUNES (disponibles partout : serveurs + MP)
# ══════════════════════════════════════════════════════════════
def everywhere(cmd):
    cmd = app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(cmd)
    cmd = app_commands.allowed_installs(guilds=True, users=True)(cmd)
    return cmd

# ══════════════════════════════════════════════════════════════
#  HELPERS IA : GEMINI (VISION & TEXTE) + GÉNÉRATION D'IMAGES
# ══════════════════════════════════════════════════════════════
async def ask_gemini(prompt: str, image_bytes: bytes = None, mime_type: str = "image/png") -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return "⚠️ Clé GEMINI_API_KEY manquante dans les variables d'environnement."

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    contents = []
    if image_bytes:
        clean_mime = mime_type.split(";")[0].strip() if mime_type else "image/png"
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=clean_mime))
    contents.append(prompt)

    last_err = None
    for m in models:
        try:
            resp = await client.aio.models.generate_content(model=m, contents=contents)
            if resp.text:
                return resp.text.strip()
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("Aucun modèle Gemini n'a pu répondre.")


async def generate_ai_image(prompt: str, style_modifier: str = "Naturel") -> tuple[bytes, str]:
    """
    Génère une image originale par IA.
    1. Tente d'abord Google GenAI Imagen 3 si GEMINI_API_KEY est configurée.
    2. Si non configurée ou en cas d'erreur de quota/accès, bascule automatiquement sur Pollinations Flux (gratuit, ultra rapide et sans clé).
    """
    enhanced_prompt = prompt
    if style_modifier and style_modifier != "Naturel":
        enhanced_prompt = f"{prompt}, {style_modifier}"

    key = os.getenv("GEMINI_API_KEY")
    # Tentative 1 : Google GenAI Imagen 3
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = await client.aio.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=enhanced_prompt,
                config=dict(number_of_images=1, output_mime_type="image/png")
            )
            if resp.generated_images and resp.generated_images[0].image:
                return resp.generated_images[0].image.image_bytes, "Google Imagen 3"
        except Exception as e:
            print(f"⚠️ Imagen 3 indisponible ({e}), bascule automatique sur Pollinations Flux...", flush=True)

    # Tentative 2 : Moteur Pollinations Flux HD (Garantie de service 24h/24)
    encoded = urllib.parse.quote(enhanced_prompt)
    seed = random.randint(1000, 9999999)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}&model=flux"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as r:
            if r.status == 200:
                data = await r.read()
                if len(data) > 1000:
                    return data, "Pollinations Flux"
    raise Exception("Impossible de contacter le service de génération d'image pour le moment.")

# ══════════════════════════════════════════════════════════════
#  /aide  —  Menu d'aide complet avec pagination
# ══════════════════════════════════════════════════════════════
HELP_PAGES = [
    {
        "title": "🦇 Batman — Page 1/4 : Essentiels",
        "color": discord.Color.dark_theme(),
        "fields": [
            ("🏓 /ping", "Latence en ms, état du bot et uptime en direct.", False),
            ("⏰ /rappel", "`duree` + `message` — Rappel automatique livré en MP (ex: 10m, 2h, 1j).", False),
            ("🦇 /batman", "Punchlines et citations légendaires du Chevalier Noir.", False),
            ("🎲 /dice", "`faces` + `nombre` — Lance des dés pour le fun ou les jeux de rôle.", False),
            ("📊 /stats", "Statistiques de ton compte (tâches, notes, uptime).", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 2/4 : To-Do & Notes Interactives",
        "color": discord.Color.blue(),
        "fields": [
            ("📋 /todo", "Tableau interactif complet : coche d'un clic, ajoute par pop-up, modifie !", False),
            ("➕ /todo_ajouter", "`tache` — Ajout ultra-rapide sans ouvrir le tableau.", False),
            ("📝 /note", "Dashboard de notes : consulte, ajoute via formulaire, ou supprime.", False),
            ("📌 /note_ajouter", "`titre` + `contenu` — Sauvegarde rapide d'une idée.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 3/4 : Utilitaires & Jeux",
        "color": discord.Color.purple(),
        "fields": [
            ("📊 /sondage", "`question` + `options` — Crée un sondage interactif avec barres de vote en direct !", False),
            ("🎮 /morpion", "Joue au Morpion (Tic-Tac-Toe) directement dans le chat avec 9 boutons !", False),
            ("⏱️ /chrono", "`duree` + `nom` — Minuteur Pomodoro qui t'alerte dès la fin.", False),
            ("🌤️ /meteo", "`ville` — Météo en temps réel sans clé d'API.", False),
            ("📈 /calcul", "`expression` — Calculatrice avancée avec fonctions mathématiques.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 4/4 : IA, Vision & Images",
        "color": discord.Color.teal(),
        "fields": [
            ("🧠 /ia", "`question` + `[image]` — Questionne Gemini ou fais analyser une photo/capture.", False),
            ("🎨 /image", "`description` + `[style]` — Génère une image IA en haute définition.", False),
            ("✨ /imagine", "`prompt` — Raccourci rapide pour générer une image artistique.", False),
            ("🌍 /traduire", "`texte` + `langue` — Traduction instantanée ultra-naturelle avec l'IA.", False),
            ("🖱️ Clic Droit Message ➜ Apps", "• **🧠 Résumer avec Batman** : Résume n'importe quel message en 1 clic.\n• **🔍 Analyser l'image (IA)** : Analyse une image postée.\n• **📝 Sauvegarder en note** : Enregistre un message directement dans tes notes !", False),
            ("🖱️ Clic Droit Profil ➜ Apps", "• **🦇 Profil & Avatar HD** : Affiche l'avatar en pleine résolution et les infos de compte.", False),
        ]
    }
]

class HelpView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.page = page
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page == len(HELP_PAGES) - 1)

    def build_embed(self) -> discord.Embed:
        p = HELP_PAGES[self.page]
        embed = discord.Embed(title=p["title"], color=p["color"])
        for name, val, inline in p["fields"]:
            embed.add_field(name=name, value=val, inline=inline)
        embed.set_footer(text=f"Page {self.page + 1}/{len(HELP_PAGES)} • Batman tourne H24 sur Render")
        return embed

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

@bot.tree.command(name="aide", description="Affiche toutes les fonctionnalités de Batman")
@everywhere
async def aide(interaction: discord.Interaction):
    view = HelpView()
    await interaction.response.send_message(embed=view.build_embed(), view=view)


# ══════════════════════════════════════════════════════════════
#  MENUS CONTEXTUELS CLIC-DROIT (Discord Apps)
# ══════════════════════════════════════════════════════════════

# 1. Clic droit sur un message -> Résumer avec Batman
@bot.tree.context_menu(name="🧠 Résumer avec Batman")
@everywhere
async def context_summarize(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content
    if not content:
        return await interaction.response.send_message("❌ Ce message ne contient pas de texte à résumer.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    prompt = f"Fais un résumé clair et percutant en 2 ou 3 points clés du texte suivant :\n\n{content}"
    try:
        summary = await ask_gemini(prompt)
        embed = discord.Embed(
            title="🧠 Résumé par Batman",
            description=summary[:1900],
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"Auteur du message original : {message.author.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# 2. Clic droit sur un message -> Sauvegarder en note
@bot.tree.context_menu(name="📝 Sauvegarder en note")
@everywhere
async def context_save_note(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content
    if not content:
        return await interaction.response.send_message("❌ Ce message ne contient aucun texte à sauvegarder.", ephemeral=True)
    
    uid = str(interaction.user.id)
    notes = load_json(NOTES_FILE)
    lst = notes.get(uid, [])
    
    title = f"Note de {message.author.display_name} ({datetime.now().strftime('%d/%m')})"
    lst.append({
        "title": title,
        "content": content[:1000],
        "date": datetime.now().strftime("%d/%m %H:%M")
    })
    notes[uid] = lst
    save_json(NOTES_FILE, notes)

    embed = discord.Embed(
        title="📝 Message sauvegardé dans tes notes !",
        description=f"**{title}**\n> {content[:200]}...",
        color=discord.Color.purple()
    )
    embed.set_footer(text="Retrouve toutes tes notes avec /note")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# 3. Clic droit sur un membre -> Profil & Avatar HD
@bot.tree.context_menu(name="🦇 Profil & Avatar HD")
@everywhere
async def context_user_info(interaction: discord.Interaction, user: discord.User):
    created_ts = int(user.created_at.timestamp())
    avatar_url = user.display_avatar.url

    embed = discord.Embed(
        title=f"🦇 Profil de {user.name}",
        description=f"**Pseudo :** `{user.display_name}`\n**ID :** `{user.id}`",
        color=discord.Color.dark_theme()
    )
    embed.add_field(name="📅 Compte créé le", value=f"<t:{created_ts}:D> (<t:{created_ts}:R>)")
    embed.add_field(name="🤖 Est un bot ?", value="Oui" if user.bot else "Non")
    embed.set_image(url=avatar_url)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Télécharger Avatar HD", url=avatar_url, emoji="🖼️"))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# 4. Clic droit sur un message -> Analyser l'image avec l'IA
@bot.tree.context_menu(name="🔍 Analyser l'image (IA)")
@everywhere
async def context_analyze_image(interaction: discord.Interaction, message: discord.Message):
    image_url = None
    mime_type = "image/png"
    img_bytes = None

    # Pièces jointes du message
    for att in message.attachments:
        ct = att.content_type or ""
        if ct.startswith("image/"):
            img_bytes = await att.read()
            mime_type = ct
            image_url = att.url
            break
        elif any(att.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
            img_bytes = await att.read()
            mime_type = "image/jpeg" if att.filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
            image_url = att.url
            break

    # Embeds d'image
    if not img_bytes and message.embeds:
        for emb in message.embeds:
            if emb.image and emb.image.url:
                image_url = emb.image.url
                break
            elif emb.thumbnail and emb.thumbnail.url:
                image_url = emb.thumbnail.url
                break
        if image_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        mime_type = resp.headers.get("Content-Type", "image/png")

    if not img_bytes:
        return await interaction.response.send_message("❌ Aucune image trouvée dans ce message à faire analyser.", ephemeral=True)

    await interaction.response.defer(thinking=True)
    prompt = "Décris et analyse cette image avec précision et clarté en français. Explique ce qu'elle montre, ses détails notables et son contexte."
    try:
        analysis = await ask_gemini(prompt, image_bytes=img_bytes, mime_type=mime_type)
        if len(analysis) > 1900:
            analysis = analysis[:1900] + "… *(suite tronquée)*"
        embed = discord.Embed(
            title="🔍 Analyse d'image par l'IA",
            description=analysis,
            color=discord.Color.teal()
        )
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text=f"Image de {message.author.display_name} • Propulsé par Gemini Vision")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`")


# ══════════════════════════════════════════════════════════════
#  SONDAGES INTERACTIFS AVEC BARRES DE PROGRESSION (/sondage)
# ══════════════════════════════════════════════════════════════
class PollView(discord.ui.View):
    def __init__(self, question: str, options: list):
        super().__init__(timeout=86400) # 24 heures
        self.question = question
        self.options = options
        self.votes = {} # user_id -> option_index

        for idx, opt in enumerate(options):
            btn = discord.ui.Button(
                label=opt[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_opt_{idx}",
                emoji=["1️⃣", "2️⃣", "3️⃣", "4️⃣"][idx]
            )
            btn.callback = self.make_callback(idx)
            self.add_item(btn)

    def make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            uid = str(interaction.user.id)
            self.votes[uid] = idx
            await interaction.response.edit_message(embed=self.build_embed())
        return callback

    def build_embed(self) -> discord.Embed:
        total = len(self.votes)
        embed = discord.Embed(
            title=f"📊 Sondage : {self.question}",
            color=discord.Color.blurple()
        )
        for idx, opt in enumerate(self.options):
            count = sum(1 for v in self.votes.values() if v == idx)
            pct = int((count / total) * 100) if total > 0 else 0
            bar = "🟩" * (pct // 10) + "⬜" * (10 - (pct // 10))
            embed.add_field(
                name=f"{['1️⃣', '2️⃣', '3️⃣', '4️⃣'][idx]} {opt}",
                value=f"{bar} **{pct}%** ({count} vote{'s' if count > 1 else ''})",
                inline=False
            )
        embed.set_footer(text=f"Total de participants : {total} • Clique sur un bouton pour voter")
        return embed

@bot.tree.command(name="sondage", description="Crée un sondage interactif avec graphiques de votes")
@everywhere
@app_commands.describe(
    question="La question du sondage",
    option1="Choix n°1",
    option2="Choix n°2",
    option3="Choix n°3 (optionnel)",
    option4="Choix n°4 (optionnel)"
)
async def sondage(interaction: discord.Interaction, question: str, option1: str, option2: str, option3: str = None, option4: str = None):
    opts = [option1, option2]
    if option3: opts.append(option3)
    if option4: opts.append(option4)
    view = PollView(question, opts)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


# ══════════════════════════════════════════════════════════════
#  MINI-JEU MORPION (Tic-Tac-Toe avec 9 boutons) (/morpion)
# ══════════════════════════════════════════════════════════════
class TicTacToeButton(discord.ui.Button):
    def __init__(self, x: int, y: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction):
        assert self.view is not None
        view: TicTacToeView = self.view
        state = view.board[self.y][self.x]
        if state != 0 or view.game_over:
            return await interaction.response.defer()

        if interaction.user != view.current_player:
            return await interaction.response.send_message("❌ Ce n'est pas ton tour !", ephemeral=True)

        # Coup joué
        if view.current_player == view.player_x:
            self.style = discord.ButtonStyle.danger
            self.label = "X"
            view.board[self.y][self.x] = 1
            view.current_player = view.player_o
        else:
            self.style = discord.ButtonStyle.primary
            self.label = "O"
            view.board[self.y][self.x] = 2
            view.current_player = view.player_x

        self.disabled = True
        winner = view.check_winner()

        if winner:
            view.game_over = True
            for child in view.children:
                child.disabled = True
            winner_user = view.player_x if winner == 1 else view.player_o
            embed = discord.Embed(
                title="🏆 Victoire au Morpion !",
                description=f"Félicitations à {winner_user.mention} qui remporte la partie !",
                color=discord.Color.gold()
            )
            await interaction.response.edit_message(embed=embed, view=view)
        elif view.is_full():
            view.game_over = True
            for child in view.children:
                child.disabled = True
            embed = discord.Embed(
                title="🤝 Match nul !",
                description="Égalité parfaite ! Bien joué aux deux joueurs.",
                color=discord.Color.orange()
            )
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            turn_str = "X" if view.current_player == view.player_x else "O"
            embed = discord.Embed(
                title="🎮 Morpion en cours",
                description=f"Au tour de {view.current_player.mention} (**{turn_str}**)",
                color=discord.Color.blue()
            )
            await interaction.response.edit_message(embed=embed, view=view)

class TicTacToeView(discord.ui.View):
    def __init__(self, player_x: discord.User, player_o: discord.User):
        super().__init__(timeout=180)
        self.player_x = player_x
        self.player_o = player_o
        self.current_player = player_x
        self.game_over = False
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def check_winner(self):
        # Lignes et colonnes
        for i in range(3):
            if self.board[i][0] == self.board[i][1] == self.board[i][2] != 0:
                return self.board[i][0]
            if self.board[0][i] == self.board[1][i] == self.board[2][i] != 0:
                return self.board[0][i]
        # Diagonales
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]
        return None

    def is_full(self):
        return all(self.board[y][x] != 0 for y in range(3) for x in range(3))

@bot.tree.command(name="morpion", description="Défie un ami ou joue au Morpion dans le chat")
@everywhere
@app_commands.describe(adversaire="Le joueur que tu veux affronter (ou toi-même)")
async def morpion(interaction: discord.Interaction, adversaire: discord.User = None):
    p2 = adversaire or interaction.user
    view = TicTacToeView(interaction.user, p2)
    embed = discord.Embed(
        title="🎮 Morpion — Partie lancée !",
        description=f"**X :** {interaction.user.mention}\n**O :** {p2.mention}\n\n👉 C'est à {interaction.user.mention} de commencer (**X**) !",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════
#  TRADUCTION PAR IA (/traduire)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="traduire", description="Traduit n'importe quel texte dans la langue de ton choix")
@everywhere
@app_commands.describe(texte="Le texte à traduire", langue="La langue cible (ex: Anglais, Espagnol, Arabe, Japonais)")
async def traduire(interaction: discord.Interaction, texte: str, langue: str):
    await interaction.response.defer(thinking=True)
    prompt = f"Traduis fidèlement et naturellement le texte suivant en {langue}. Ne donne QUE la traduction, sans intro ni commentaire :\n\n{texte}"
    try:
        trad = await ask_gemini(prompt)
        embed = discord.Embed(title=f"🌍 Traduction ➜ {langue.capitalize()}", color=discord.Color.teal())
        embed.add_field(name="Texte original", value=texte[:1000], inline=False)
        embed.add_field(name="Traduction", value=trad[:1000], inline=False)
        embed.set_footer(text="Traduit par Gemini 3.1 Flash-Lite")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur de traduction : `{e}`")


# ══════════════════════════════════════════════════════════════
#  PUNCHLINES & CITATIONS BATMAN (/batman)
# ══════════════════════════════════════════════════════════════
BATMAN_QUOTES = [
    ("« Ce n'est pas qui je suis à l'intérieur, mais ce que je fais qui me définit. »", "Batman Begins"),
    ("« Soit on meurt en héros, soit on vit assez longtemps pour se voir devenir le méchant. »", "The Dark Knight"),
    ("« La nuit est plus sombre juste avant l'aube. Mais je vous le promets, l'aube se lèvera. »", "The Dark Knight"),
    ("« Pourquoi tombons-nous, Bruce ? Pour mieux apprendre à nous relever. »", "Thomas Wayne"),
    ("« Je suis la vengeance. Je suis la nuit. Je suis Batman ! »", "Batman: La Série Animée"),
    ("« Un héros peut être n'importe qui. Même un homme faisant une chose aussi simple que poser un manteau sur les épaules d'un enfant. »", "The Dark Knight Rises"),
    ("« Gotham a besoin de toi. Reste concentré et termine tes /todo. »", "Alfred Pennyworth")
]

@bot.tree.command(name="batman", description="Reçois une citation légendaire de Batman et Gotham")
@everywhere
async def batman_quote(interaction: discord.Interaction):
    quote, src = random.choice(BATMAN_QUOTES)
    embed = discord.Embed(
        title="🦇 Conseil du Chevalier Noir",
        description=f"### {quote}\n\n*— {src}*",
        color=discord.Color.dark_theme()
    )
    embed.set_footer(text="Gardien de Gotham • Actif H24")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /ping
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ping", description="Vérifie la réactivité du bot")
@everywhere
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    color = discord.Color.green() if latency < 150 else discord.Color.orange()
    embed = discord.Embed(
        title="🏓 Pong !",
        description=f"**Latence :** `{latency} ms`\n**Statut :** {'🟢 Parfait' if latency < 150 else '🟡 Bon'}",
        color=color
    )
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    h, r = divmod(uptime, 3600); m, s = divmod(r, 60)
    embed.add_field(name="⏳ Uptime", value=f"`{h}h {m}m {s}s`")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /rappel  —  Timer one-shot
# ══════════════════════════════════════════════════════════════
def parse_duration(s: str) -> int:
    s = s.strip().lower()
    m = re.match(r"^(\d+)\s*(s|m|h|j|d)?$", s)
    if not m: return 0
    v, u = int(m.group(1)), m.group(2)
    return v * {"s": 1, "m": 60, "h": 3600, "j": 86400, "d": 86400}.get(u or "s", 1)

@bot.tree.command(name="rappel", description="Programme un rappel (livré en MP)")
@everywhere
@app_commands.describe(duree="Durée : 30s, 10m, 2h, 1j…", message="Ce que je dois te rappeler")
async def rappel(interaction: discord.Interaction, duree: str, message: str):
    secs = parse_duration(duree)
    if secs <= 0:
        return await interaction.response.send_message("❌ Format invalide. Ex : `10m`, `2h`, `1j`", ephemeral=True)
    if secs > 86400 * 7:
        return await interaction.response.send_message("❌ Maximum 7 jours.", ephemeral=True)

    embed_confirm = discord.Embed(
        title="⏰ Rappel programmé !",
        description=f"Je te préviendrai dans **{duree}**\n\n> {message}",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed_confirm)

    async def fire():
        await asyncio.sleep(secs)
        embed = discord.Embed(
            title="⏰ C'est l'heure !",
            description=f"{interaction.user.mention} 👉 **{message}**",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        try:
            await interaction.user.send(embed=embed)
        except Exception:
            try:
                await interaction.channel.send(content=interaction.user.mention, embed=embed)
            except Exception:
                pass

    asyncio.create_task(fire())


# ══════════════════════════════════════════════════════════════
#  /chrono  —  Pomodoro / minuteur
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="chrono", description="Lance un chrono Pomodoro (alerte en MP)")
@everywhere
@app_commands.describe(duree="Durée : 25m, 1h, etc.", nom="Nom de la session (ex: Révisions)")
async def chrono(interaction: discord.Interaction, duree: str, nom: str = "Session"):
    secs = parse_duration(duree)
    if secs <= 0 or secs > 7200:
        return await interaction.response.send_message("❌ Durée invalide (max 2h).", ephemeral=True)

    embed = discord.Embed(
        title="⏱️ Chrono lancé !",
        description=f"**{nom}** — `{duree}`\nConcentre-toi ! Je te préviendrai à la fin. 🧘",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)

    async def fire():
        await asyncio.sleep(secs)
        embed_done = discord.Embed(
            title="✅ Temps écoulé !",
            description=f"**{nom}** est terminé(e) ! Bien joué 🎉\nPense à faire une pause.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        try:
            await interaction.user.send(embed=embed_done)
        except Exception:
            try:
                await interaction.channel.send(content=interaction.user.mention, embed=embed_done)
            except Exception:
                pass

    asyncio.create_task(fire())


# ══════════════════════════════════════════════════════════════
#  /dice  —  Dés
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="dice", description="Lance un dé à N faces")
@everywhere
@app_commands.describe(faces="Nombre de faces (défaut : 6)", nombre="Combien de dés (défaut : 1)")
async def dice(interaction: discord.Interaction, faces: int = 6, nombre: int = 1):
    if faces < 2 or faces > 1000:
        return await interaction.response.send_message("❌ Entre 2 et 1000 faces.", ephemeral=True)
    if nombre < 1 or nombre > 20:
        return await interaction.response.send_message("❌ Entre 1 et 20 dés.", ephemeral=True)
    rolls = [random.randint(1, faces) for _ in range(nombre)]
    total = sum(rolls)
    rolls_str = " + ".join(f"`{r}`" for r in rolls)
    embed = discord.Embed(
        title=f"🎲 {nombre}d{faces}",
        description=f"{rolls_str}\n**Total : `{total}`**",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /calcul  —  Calculatrice
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="calcul", description="Calculatrice avancée")
@everywhere
@app_commands.describe(expression="Ex : (3+5)*2, 2**10, sqrt(144)")
async def calcul(interaction: discord.Interaction, expression: str):
    allowed = set("0123456789+-*/().%, eE")
    safe_funcs = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    safe_funcs["abs"] = abs; safe_funcs["round"] = round
    clean = expression.replace("^", "**").replace(",", ".")
    if any(c not in allowed and not c.isalpha() for c in clean):
        return await interaction.response.send_message("❌ Expression non autorisée.", ephemeral=True)
    try:
        result = eval(clean, {"__builtins__": {}}, safe_funcs)
        embed = discord.Embed(
            title="📈 Calculatrice",
            description=f"**`{expression}`**\n= **`{result}`**",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /meteo  —  Météo
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="meteo", description="Météo actuelle de n'importe quelle ville")
@everywhere
@app_commands.describe(ville="Nom de la ville (ex: Paris, Tokyo, Alger…)")
async def meteo(interaction: discord.Interaction, ville: str):
    await interaction.response.defer(thinking=True)
    try:
        async with aiohttp.ClientSession() as session:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={ville}&count=1&language=fr"
            async with session.get(geo_url) as r:
                geo = await r.json()
            if not geo.get("results"):
                return await interaction.followup.send(f"❌ Ville introuvable : **{ville}**", ephemeral=True)
            loc = geo["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            city_name = loc.get("name", ville)
            country   = loc.get("country", "")

            wx_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,apparent_temperature,weathercode,"
                "windspeed_10m,relativehumidity_2m&timezone=auto"
            )
            async with session.get(wx_url) as r:
                wx = await r.json()
            cur = wx["current"]
            code = cur["weathercode"]
            ICONS = {
                0:"☀️ Ciel dégagé", 1:"🌤️ Ensoleillé", 2:"⛅ Partiellement couvert", 3:"☁️ Couvert",
                45:"🌫️ Brouillard", 48:"🌫️ Brouillard glacé",
                51:"🌦️ Bruine légère", 53:"🌦️ Bruine", 55:"🌧️ Bruine dense",
                61:"🌧️ Pluie légère", 63:"🌧️ Pluie", 65:"🌧️ Pluie forte",
                71:"🌨️ Neige légère", 73:"❄️ Neige", 75:"❄️ Neige forte",
                80:"🌧️ Averses", 81:"🌧️ Fortes averses", 82:"⛈️ Averses violentes",
                95:"⛈️ Orage", 96:"⛈️ Orage et grêle", 99:"⛈️ Orage violent"
            }
            desc = ICONS.get(code, f"Code météo {code}")
            embed = discord.Embed(
                title=f"🌍 Météo — {city_name}, {country}",
                description=f"**{desc}**",
                color=discord.Color.from_rgb(100, 180, 255)
            )
            embed.add_field(name="🌡️ Température", value=f"`{cur['temperature_2m']}°C`")
            embed.add_field(name="🤔 Ressentie", value=f"`{cur['apparent_temperature']}°C`")
            embed.add_field(name="💧 Humidité", value=f"`{cur['relativehumidity_2m']}%`")
            embed.add_field(name="💨 Vent", value=f"`{cur['windspeed_10m']} km/h`")
            embed.set_footer(text="Source : Open-Meteo • Données en direct")
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur météo : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /stats  —  Statistiques
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="stats", description="Résumé de tes activités Batman")
@everywhere
async def stats(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    todos = load_json(TODOS_FILE).get(uid, [])
    notes = load_json(NOTES_FILE).get(uid, [])
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    h, r = divmod(uptime, 3600); m, s = divmod(r, 60)
    embed = discord.Embed(
        title=f"📊 Statistiques — {interaction.user.display_name}",
        color=discord.Color.gold()
    )
    embed.add_field(name="✅ Tâches en cours", value=f"`{len(todos)}`")
    embed.add_field(name="📝 Notes sauvegardées", value=f"`{len(notes)}`")
    embed.add_field(name="⏳ Uptime du bot", value=f"`{h}h {m}m {s}s`")
    embed.add_field(name="🤖 Bot", value=f"`{bot.user}`")
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text="Batman — Hébergé H24 sur Render")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /todo  —  To-Do interactive
# ══════════════════════════════════════════════════════════════
def create_todo_embed(user_name: str, tasks: list) -> discord.Embed:
    embed = discord.Embed(title=f"📋 To-Do — {user_name}", color=discord.Color.blue())
    if not tasks:
        embed.description = "🎉 **Aucune tâche en cours !**\nClique sur le bouton vert **➕ Ajouter** ci-dessous."
    else:
        lines = [f"`{i}.` {t['task']} *(le {t.get('date','')})*"
                 for i, t in enumerate(tasks, 1)]
        embed.description = "\n".join(lines)
        embed.set_footer(text="Coche une tâche dans le menu déroulant ci-dessous ✅")
    return embed

class AddTaskModal(discord.ui.Modal, title="➕ Nouvelle tâche"):
    task = discord.ui.TextInput(
        label="Quelle tâche veux-tu ajouter ?",
        placeholder="Ex: Réviser maths, appeler Pierre…",
        max_length=200
    )

    def __init__(self, uid: str):
        super().__init__(); self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        todos = load_json(TODOS_FILE)
        lst = todos.get(self.uid, [])
        lst.append({"task": self.task.value.strip(), "date": datetime.now().strftime("%d/%m %H:%M")})
        todos[self.uid] = lst; save_json(TODOS_FILE, todos)
        await interaction.response.edit_message(
            embed=create_todo_embed(interaction.user.display_name, lst),
            view=TodoView(self.uid, lst)
        )

class EditTaskModal(discord.ui.Modal, title="✏️ Modifier une tâche"):
    new_text = discord.ui.TextInput(label="Nouveau texte", max_length=200)

    def __init__(self, uid: str, idx: int, old: str):
        super().__init__()
        self.uid = uid; self.idx = idx
        self.new_text.default = old

    async def on_submit(self, interaction: discord.Interaction):
        todos = load_json(TODOS_FILE)
        lst = todos.get(self.uid, [])
        if 0 <= self.idx < len(lst):
            lst[self.idx]["task"] = self.new_text.value.strip()
            todos[self.uid] = lst; save_json(TODOS_FILE, todos)
        await interaction.response.edit_message(
            embed=create_todo_embed(interaction.user.display_name, lst),
            view=TodoView(self.uid, lst)
        )

class TodoCheckSelect(discord.ui.Select):
    def __init__(self, uid: str, tasks: list):
        self.uid = uid
        opts = [
            discord.SelectOption(label=f"{i}. {t['task'][:75]}", value=str(i-1),
                                 description=f"le {t.get('date','')}"[:100], emoji="⬜")
            for i, t in enumerate(tasks[:25], 1)
        ]
        super().__init__(placeholder="✅ Cocher une tâche terminée…", options=opts, row=0)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌ Pas ta liste !", ephemeral=True)
        idx = int(self.values[0])
        todos = load_json(TODOS_FILE)
        lst = todos.get(self.uid, [])
        done = lst.pop(idx)
        todos[self.uid] = lst; save_json(TODOS_FILE, todos)
        await interaction.response.edit_message(
            embed=create_todo_embed(interaction.user.display_name, lst),
            view=TodoView(self.uid, lst)
        )

class TodoEditSelect(discord.ui.Select):
    def __init__(self, uid: str, tasks: list):
        self.uid = uid
        opts = [
            discord.SelectOption(label=f"✏️ {i}. {t['task'][:70]}", value=str(i-1), emoji="✏️")
            for i, t in enumerate(tasks[:25], 1)
        ]
        super().__init__(placeholder="✏️ Modifier une tâche…", options=opts, row=1)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌ Pas ta liste !", ephemeral=True)
        idx = int(self.values[0])
        todos = load_json(TODOS_FILE)
        lst = todos.get(self.uid, [])
        await interaction.response.send_modal(EditTaskModal(self.uid, idx, lst[idx]["task"]))

class TodoView(discord.ui.View):
    def __init__(self, uid: str, tasks: list):
        super().__init__(timeout=600)
        self.uid = uid
        if tasks:
            self.add_item(TodoCheckSelect(uid, tasks))
            self.add_item(TodoEditSelect(uid, tasks))

    @discord.ui.button(label="Ajouter", style=discord.ButtonStyle.success, emoji="➕", row=2)
    async def add_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_modal(AddTaskModal(self.uid))

    @discord.ui.button(label="Tout effacer", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
    async def clear_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌", ephemeral=True)
        todos = load_json(TODOS_FILE)
        todos[self.uid] = []; save_json(TODOS_FILE, todos)
        await interaction.response.edit_message(
            embed=create_todo_embed(interaction.user.display_name, []),
            view=TodoView(self.uid, [])
        )

    @discord.ui.button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄", row=2)
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌", ephemeral=True)
        lst = load_json(TODOS_FILE).get(self.uid, [])
        await interaction.response.edit_message(
            embed=create_todo_embed(interaction.user.display_name, lst),
            view=TodoView(self.uid, lst)
        )

@bot.tree.command(name="todo", description="Ouvre ton tableau de bord de tâches interactif")
@everywhere
async def todo(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    lst = load_json(TODOS_FILE).get(uid, [])
    await interaction.response.send_message(embed=create_todo_embed(interaction.user.display_name, lst), view=TodoView(uid, lst))

@bot.tree.command(name="todo_ajouter", description="Ajoute une tâche rapidement")
@everywhere
@app_commands.describe(tache="La tâche à ajouter")
async def todo_ajouter(interaction: discord.Interaction, tache: str):
    uid = str(interaction.user.id)
    todos = load_json(TODOS_FILE)
    lst = todos.get(uid, [])
    lst.append({"task": tache, "date": datetime.now().strftime("%d/%m %H:%M")})
    todos[uid] = lst; save_json(TODOS_FILE, todos)
    await interaction.response.send_message(f"✅ Tâche ajoutée : **{tache}** ({len(lst)} total)", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /note  —  Notes interactives
# ══════════════════════════════════════════════════════════════
def create_notes_embed(user_name: str, notes: list) -> discord.Embed:
    embed = discord.Embed(title=f"📚 Notes — {user_name}", color=discord.Color.purple())
    if not notes:
        embed.description = "📭 Aucune note.\nClique sur **➕ Nouvelle note** ci-dessous."
    else:
        for n in notes[-8:]:
            embed.add_field(
                name=f"📌 {n['title']} ({n.get('date', '')})",
                value=n['content'][:200] + ("…" if len(n['content']) > 200 else ""),
                inline=False
            )
        embed.set_footer(text=f"{len(notes)} note(s) au total • Utilise le menu pour en supprimer une")
    return embed

class AddNoteModal(discord.ui.Modal, title="📝 Nouvelle note"):
    title_in = discord.ui.TextInput(label="Titre", max_length=100)
    content  = discord.ui.TextInput(label="Contenu", style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, uid: str):
        super().__init__(); self.uid = uid

    async def on_submit(self, interaction: discord.Interaction):
        notes = load_json(NOTES_FILE)
        lst = notes.get(self.uid, [])
        lst.append({"title": self.title_in.value.strip(), "content": self.content.value.strip(),
                    "date": datetime.now().strftime("%d/%m %H:%M")})
        notes[self.uid] = lst; save_json(NOTES_FILE, notes)
        await interaction.response.edit_message(
            embed=create_notes_embed(interaction.user.display_name, lst),
            view=NotesView(self.uid, lst)
        )

class DeleteNoteSelect(discord.ui.Select):
    def __init__(self, uid: str, notes: list):
        self.uid = uid
        opts = [
            discord.SelectOption(label=f"🗑️ {n['title'][:70]}", value=str(i), emoji="🗑️")
            for i, n in enumerate(notes[:25])
        ]
        super().__init__(placeholder="🗑️ Supprimer une note…", options=opts, row=0)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌", ephemeral=True)
        idx = int(self.values[0])
        notes = load_json(NOTES_FILE)
        lst = notes.get(self.uid, [])
        lst.pop(idx)
        notes[self.uid] = lst; save_json(NOTES_FILE, notes)
        await interaction.response.edit_message(
            embed=create_notes_embed(interaction.user.display_name, lst),
            view=NotesView(self.uid, lst)
        )

class NotesView(discord.ui.View):
    def __init__(self, uid: str, notes: list):
        super().__init__(timeout=600)
        self.uid = uid
        if notes:
            self.add_item(DeleteNoteSelect(uid, notes))

    @discord.ui.button(label="Nouvelle note", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def add_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌", ephemeral=True)
        await interaction.response.send_modal(AddNoteModal(self.uid))

    @discord.ui.button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        lst = load_json(NOTES_FILE).get(self.uid, [])
        await interaction.response.edit_message(
            embed=create_notes_embed(interaction.user.display_name, lst),
            view=NotesView(self.uid, lst)
        )

@bot.tree.command(name="note", description="Ouvre ton tableau de bord de notes interactif")
@everywhere
async def note(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    lst = load_json(NOTES_FILE).get(uid, [])
    await interaction.response.send_message(embed=create_notes_embed(interaction.user.display_name, lst), view=NotesView(uid, lst))

@bot.tree.command(name="note_ajouter", description="Ajoute une note rapidement via commande")
@everywhere
@app_commands.describe(titre="Titre de la note", contenu="Contenu de la note")
async def note_ajouter(interaction: discord.Interaction, titre: str, contenu: str):
    uid = str(interaction.user.id)
    notes = load_json(NOTES_FILE)
    lst = notes.get(uid, [])
    lst.append({"title": titre, "content": contenu, "date": datetime.now().strftime("%d/%m %H:%M")})
    notes[uid] = lst; save_json(NOTES_FILE, notes)
    await interaction.response.send_message(f"📝 Note **\"{titre}\"** sauvegardée !", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /ia  —  Assistant IA Gemini (Texte & Vision Multimodale)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ia", description="Pose une question à l'IA ou fais analyser une image")
@everywhere
@app_commands.describe(
    question="Ta question, texte à résumer ou consigne d'analyse",
    image="Image optionnelle à envoyer pour analyse (PNG, JPG, WEBP...)"
)
async def ia_command(
    interaction: discord.Interaction,
    question: str,
    image: discord.Attachment = None
):
    await interaction.response.defer(thinking=True)
    try:
        img_bytes = None
        mime_type = "image/png"
        if image is not None:
            ct = image.content_type or ""
            is_image = ct.startswith("image/") or any(
                image.filename.lower().endswith(ext)
                for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]
            )
            if not is_image:
                return await interaction.followup.send("❌ Le fichier fourni doit être une image valide (PNG, JPG, WEBP, GIF).")
            img_bytes = await image.read()
            mime_type = ct if ct.startswith("image/") else "image/png"

        answer = await ask_gemini(question, image_bytes=img_bytes, mime_type=mime_type)
        if len(answer) > 1900:
            answer = answer[:1900] + "… *(suite tronquée)*"
        embed = discord.Embed(title="🧠 Réponse IA", description=answer, color=discord.Color.teal())
        if image is not None:
            embed.set_thumbnail(url=image.url)
        footer = f"Q: {question[:75]}"
        if image is not None:
            footer += " 📸 (avec image)"
        footer += " • Propulsé par Gemini"
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`")


# ══════════════════════════════════════════════════════════════
#  /image & /imagine  —  Génération d'images par IA
# ══════════════════════════════════════════════════════════════
IMAGE_STYLES = [
    app_commands.Choice(name="🎨 Standard / Naturel", value="Naturel"),
    app_commands.Choice(name="📸 Photoréaliste", value="photorealistic, 8k photography, highly detailed, sharp focus"),
    app_commands.Choice(name="🦇 Batman / Gotham Dark", value="dark gothic style, Batman comics noir, moody dramatic shadows, cinematic rain"),
    app_commands.Choice(name="🏮 Anime / Manga", value="anime aesthetic, Makoto Shinkai style, vibrant colors, detailed line art"),
    app_commands.Choice(name="⚡ Cyberpunk", value="cyberpunk city, neon lights, futuristic, rainy night, synthwave"),
    app_commands.Choice(name="🖌️ Peinture à l'huile", value="oil painting on canvas, expressive brush strokes, classical art"),
    app_commands.Choice(name="🕹️ Pixel Art", value="pixel art 32-bit, retro gaming aesthetic")
]

@bot.tree.command(name="image", description="Génère une image originale par intelligence artificielle")
@everywhere
@app_commands.describe(
    description="Ce que tu veux voir sur l'image (ex: Batman contemplant Gotham sous la pluie)",
    style="Style artistique optionnel pour l'image"
)
@app_commands.choices(style=IMAGE_STYLES)
async def image_command(
    interaction: discord.Interaction,
    description: str,
    style: app_commands.Choice[str] = None
):
    await interaction.response.defer(thinking=True)
    try:
        chosen_style = style.value if style else "Naturel"
        style_label = style.name if style else "Standard"
        img_bytes, engine = await generate_ai_image(description, chosen_style)

        file = discord.File(io.BytesIO(img_bytes), filename="batman_art.png")
        embed = discord.Embed(
            title="🎨 Image générée par l'IA",
            description=f"**Prompt :** {description}\n**Style :** {style_label}",
            color=discord.Color.dark_theme()
        )
        embed.set_image(url="attachment://batman_art.png")
        embed.set_footer(text=f"Demandé par {interaction.user.display_name} • Moteur : {engine}")
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur lors de la génération de l'image : `{e}`")


@bot.tree.command(name="imagine", description="Génère une image artistique par IA (alias de /image)")
@everywhere
@app_commands.describe(prompt="Description de l'image à imaginer")
async def imagine_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer(thinking=True)
    try:
        img_bytes, engine = await generate_ai_image(prompt, "Naturel")
        file = discord.File(io.BytesIO(img_bytes), filename="imagine_art.png")
        embed = discord.Embed(
            title="✨ Imagination IA",
            description=f"> {prompt}",
            color=discord.Color.purple()
        )
        embed.set_image(url="attachment://imagine_art.png")
        embed.set_footer(text=f"Demandé par {interaction.user.display_name} • Moteur : {engine}")
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
async def main():
    if not TOKEN or TOKEN == "colle_ton_token_ici":
        print("❌ DISCORD_TOKEN manquant dans .env !", flush=True); return
    await start_web_server()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Arrêt.", flush=True)
