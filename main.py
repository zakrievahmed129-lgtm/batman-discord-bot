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
MEMORY_FILE = os.path.join(DATA_DIR, "ai_memory.json")
STYLES_FILE = os.path.join(DATA_DIR, "user_styles.json")
AFK_FILE    = os.path.join(DATA_DIR, "afk.json")

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
intents.message_content = True
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

# ─────────────────── GESTIONNAIRE D'ERREURS GLOBAL ─────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Doucement ! Réessaie dans `{error.retry_after:.1f}` secondes."
    elif isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Tu n'as pas les permissions requises pour exécuter cette commande."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ Le bot n'a pas les permissions nécessaires sur ce serveur."
    else:
        msg = f"⚠️ Une erreur est survenue : `{error}`"

    embed = discord.Embed(title="🦇 Batman — Erreur", description=msg, color=discord.Color.red())
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        pass

# ─────────────────────── ON MESSAGE (AFK) ─────────────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    uid = str(message.author.id)
    afk_data = load_json(AFK_FILE)

    # 1. Si l'auteur du message était en mode AFK, on le retire dès qu'il parle
    if uid in afk_data:
        since_ts = afk_data[uid].get("since", int(datetime.now().timestamp()))
        del afk_data[uid]
        save_json(AFK_FILE, afk_data)
        try:
            await message.channel.send(
                f"👋 Bon retour {message.author.mention} ! Ton mode AFK a été désactivé (tu étais absent depuis <t:{since_ts}:R>).",
                delete_after=8
            )
        except Exception:
            pass

    # 2. Si un utilisateur mentionné dans le message est AFK
    if message.mentions:
        for user in message.mentions:
            u_id = str(user.id)
            if u_id != uid and u_id in afk_data:
                u_info = afk_data[u_id]
                reason = u_info.get("reason", "Absent")
                since_ts = u_info.get("since", int(datetime.now().timestamp()))
                try:
                    embed_afk = discord.Embed(
                        description=f"💤 **{user.display_name}** est actuellement absent(e) : *« {reason} »* (parti <t:{since_ts}:R>)",
                        color=discord.Color.light_grey()
                    )
                    await message.channel.send(embed=embed_afk, delete_after=12)
                except Exception:
                    pass

    # 3. Apprentissage automatique discret du style de langage de l'auteur
    content = message.clean_content or message.content
    if content and len(content) > 3 and not content.startswith(("/", "!", ".")):
        try:
            styles = load_json(STYLES_FILE)
            u_style = styles.get(uid, {"label": "Apprentissage continu", "rules": DEFAULT_STYLE, "recent_messages": []})
            recent = u_style.get("recent_messages", [])
            recent.append(content[:250])
            u_style["recent_messages"] = recent[-20:] # garde les 20 derniers messages réels
            styles[uid] = u_style
            save_json(STYLES_FILE, styles)
        except Exception:
            pass

    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════
#  DÉCORATIONS COMMUNES (disponibles partout : serveurs + MP)
# ══════════════════════════════════════════════════════════════
def everywhere(cmd):
    cmd = app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(cmd)
    cmd = app_commands.allowed_installs(guilds=True, users=True)(cmd)
    return cmd

# ══════════════════════════════════════════════════════════════
#  HELPERS IA : GEMINI (VISION & TEXTE) + MÉMOIRE CONVERSATIONNELLE
# ══════════════════════════════════════════════════════════════
async def ask_gemini(
    prompt: str,
    image_bytes: bytes = None,
    mime_type: str = "image/png",
    history: list = None,
    system_instruction: str = None
) -> str:
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
    # 1. Contexte d'historique de conversation (mémoire)
    if history:
        for turn in history[-10:]:
            r = turn.get("role", "user")
            t = turn.get("text", "")
            if t:
                contents.append(types.Content(role=r, parts=[types.Part.from_text(text=t)]))

    # 2. Tour actuel (texte + image optionnelle)
    user_parts = []
    if image_bytes:
        clean_mime = mime_type.split(";")[0].strip() if mime_type else "image/png"
        user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type=clean_mime))
    user_parts.append(types.Part.from_text(text=prompt))
    contents.append(types.Content(role="user", parts=user_parts))

    config = types.GenerateContentConfig(system_instruction=system_instruction) if system_instruction else None

    last_err = None
    for m in models:
        try:
            resp = await client.aio.models.generate_content(model=m, contents=contents, config=config)
            if resp.text:
                return resp.text.strip()
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("Aucun modèle Gemini n'a pu répondre.")


# ───────────────── GESTION DE LA MÉMOIRE IA ───────────────────
def get_user_memory(uid: str) -> list:
    mem = load_json(MEMORY_FILE)
    return mem.get(uid, {}).get("history", [])

def append_user_memory(uid: str, user_text: str, ai_text: str):
    mem = load_json(MEMORY_FILE)
    u_data = mem.get(uid, {"history": []})
    hist = u_data.get("history", [])
    hist.append({"role": "user", "text": user_text[:800]})
    hist.append({"role": "model", "text": ai_text[:1200]})
    u_data["history"] = hist[-12:] # 6 allers-retours max pour rester rapide
    u_data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    mem[uid] = u_data
    save_json(MEMORY_FILE, mem)

def reset_user_memory(uid: str):
    mem = load_json(MEMORY_FILE)
    if uid in mem:
        mem[uid]["history"] = []
        save_json(MEMORY_FILE, mem)


# ─────────────── GESTION DU STYLE DE LANGAGE ──────────────────
DEFAULT_STYLE = "Naturel, décontracté, tutoiement amical, phrases claires, emojis légers"

PRESET_STYLES = {
    "familier": {
        "label": "🤙 Familier & Argot urbain",
        "rules": "Argot moderne (wesh, frérot, mdrr, chaud, tranquille, sah, bg), phrases courtes, minuscules, direct, détendu."
    },
    "cool": {
        "label": "🤝 Cool & Amical",
        "rules": "Chaleureux, bienveillant, tutoiement spontané, emojis sympas, positif et amical."
    },
    "pro": {
        "label": "💼 Professionnel & Courtois",
        "rules": "Poli, soigné, sans fautes, vouvoiement/tutoiement courtois, précis, bien articulé et orienté solution."
    },
    "batman": {
        "label": "🦇 Batman / Chevalier Noir",
        "rules": "Sombre, laconique, percutant, voix grave, direct, aucune fioriture inutile."
    },
    "sarcasme": {
        "label": "⚡ Sarcastique & Piquant",
        "rules": "Second degré aiguisé, ironique, répartie affûtée, taquin et incisif sans vulgarité."
    }
}

def get_user_style_description(uid: str) -> str:
    styles = load_json(STYLES_FILE)
    if uid in styles:
        u_data = styles[uid]
        rules = u_data.get("rules", DEFAULT_STYLE)
        recent = u_data.get("recent_messages", [])
        if recent:
            samples_str = "\n".join(f"- « {m} »" for m in recent[-12:])
            return f"Règles stylistiques :\n{rules}\n\nExemples récents de ses vrais messages dans le chat (à imiter fidèlement) :\n{samples_str}"
        return rules
    return DEFAULT_STYLE

def get_user_style_label(uid: str) -> str:
    styles = load_json(STYLES_FILE)
    if uid in styles:
        return styles[uid].get("label", "Personnalisé")
    return "Standard (Défaut)"

def set_user_style(uid: str, label: str, rules: str, samples: str = "", recent_messages: list = None):
    styles = load_json(STYLES_FILE)
    existing = styles.get(uid, {})
    styles[uid] = {
        "label": label,
        "rules": rules,
        "samples": samples,
        "recent_messages": recent_messages if recent_messages is not None else existing.get("recent_messages", []),
        "updated": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    save_json(STYLES_FILE, styles)


async def generate_ai_image(
    prompt: str,
    style_modifier: str = "Naturel",
    aspect_ratio: str = "1:1"
) -> tuple[bytes, str]:
    """
    Génère une image originale par IA.
    1. Tente d'abord Google GenAI Imagen 3 si GEMINI_API_KEY est configurée.
    2. Si non configurée ou en cas d'erreur de quota/accès, bascule automatiquement sur Pollinations Flux (gratuit, ultra rapide et sans clé).
    """
    enhanced_prompt = prompt
    if style_modifier and style_modifier != "Naturel":
        enhanced_prompt = f"{prompt}, {style_modifier}"

    dim_map = {
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1024, 768),
        "3:4": (768, 1024)
    }
    width, height = dim_map.get(aspect_ratio, (1024, 1024))

    key = os.getenv("GEMINI_API_KEY")
    # Tentative 1 : Google GenAI Imagen 3
    if key:
        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = await client.aio.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=enhanced_prompt,
                config=dict(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio=aspect_ratio
                )
            )
            if resp.generated_images and resp.generated_images[0].image:
                return resp.generated_images[0].image.image_bytes, "Google Imagen 3"
        except Exception as e:
            print(f"⚠️ Imagen 3 indisponible ({e}), bascule automatique sur Pollinations Flux...", flush=True)

    # Tentative 2 : Moteur Pollinations Flux HD (Garantie de service 24h/24)
    encoded = urllib.parse.quote(enhanced_prompt)
    seed = random.randint(1000, 9999999)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&seed={seed}&model=flux"
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
        "title": "🦇 Batman — Page 1/5 : Essentiels & Mode Absent",
        "color": discord.Color.dark_theme(),
        "fields": [
            ("🏓 /ping", "Latence en ms, état du bot et uptime en direct.", False),
            ("💤 /afk", "`[raison]` — Active ton mode absence ; Batman prévient ceux qui te mentionnent.", False),
            ("⏰ /rappel", "`duree` + `message` — Rappel automatique livré en MP (ex: 10m, 2h, 1j).", False),
            ("🦇 /batman", "Punchlines et citations légendaires du Chevalier Noir.", False),
            ("🎲 /dice", "`faces` + `nombre` — Lance des dés pour le fun ou les jeux de rôle.", False),
            ("📊 /stats", "Statistiques de ton compte (tâches, notes, uptime).", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 2/5 : To-Do & Notes Interactives",
        "color": discord.Color.blue(),
        "fields": [
            ("📋 /todo", "Tableau interactif complet : coche d'un clic, ajoute par pop-up, modifie !", False),
            ("➕ /todo_ajouter", "`tache` — Ajout ultra-rapide sans ouvrir le tableau.", False),
            ("📝 /note", "Dashboard de notes : consulte, ajoute via formulaire, ou supprime.", False),
            ("📌 /note_ajouter", "`titre` + `contenu` — Sauvegarde rapide d'une idée.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 3/5 : Utilitaires & Jeux",
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
        "title": "🦇 Batman — Page 4/5 : Conversation, Clone de Style & Mémoire",
        "color": discord.Color.teal(),
        "fields": [
            ("🧠 /ia", "`question` + `[image]` — Discussion avec mémoire continue et vision multimodale.", False),
            ("💭 /ia_memoire", "Consulte ce que l'IA a en mémoire sur tes conversations passées.", False),
            ("🧹 /ia_reset", "Efface l'historique de discussion pour repartir sur une conversation neuve.", False),
            ("🎨 /mon_style", "`[preset]` + `[description]` — Configure ton style d'écriture pour les réponses auto.", False),
            ("🔍 /scanner_mon_style", "Scanne automatiquement tes messages récents pour apprendre ton style !", False),
            ("💬 /reponds_pour_moi", "`message` + `[intention]` — Génère 3 réponses calibrées selon ton style.", False),
            ("✍️ /reformuler", "`texte` + `style` — Reformule une phrase (Pro, Clash, Batman, Diplomate...).", False),
            ("⚡ /repartie", "`sujet` + `[intensite]` — Génère des réparties et punchlines légendaires.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 5/5 : Images IA & Clic-Droit Magique",
        "color": discord.Color.gold(),
        "fields": [
            ("🎨 /image", "`description` + `[style]` + `[format]` — Génère une image IA avec boutons interactifs.", False),
            ("✨ /imagine", "`prompt` — Raccourci de création artistique par IA.", False),
            ("🌍 /traduire", "`texte` + `langue` — Traduction instantanée ultra-naturelle avec l'IA.", False),
            ("🖱️ Clic Droit Message ➜ Apps", "• **💬 Répondre à ma place** : Analyse le message et propose 3 réponses dans ton style.\n• **🎭 Analyser le ton & sous-entendus** : Décode les non-dits et le ton émotionnel.\n• **🧠 Résumer avec Batman** : Résume un pavé en 1 clic.\n• **🔍 Analyser l'image (IA)** : Analyse n'importe quelle photo ou capture.\n• **📝 Sauvegarder en note** : Enregistre le message dans ton carnet.", False),
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


# 5. Clic droit sur un message -> Répondre à ma place (Ghostwriter)
class GhostwriterView(discord.ui.View):
    def __init__(self, target_message: discord.Message, author_id: int, opt1: str, opt2: str, opt3: str):
        super().__init__(timeout=600)
        self.target_message = target_message
        self.author_id = author_id
        self.opt1 = opt1
        self.opt2 = opt2
        self.opt3 = opt3

    async def _send_reply(self, interaction: discord.Interaction, text: str, opt_num: int):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)

        content = f"> 💬 *En réponse à {self.target_message.author.display_name} :*\n{text}"
        sent = False

        # Tentative 1 : Via interaction publique (support User Apps)
        try:
            await interaction.response.send_message(content=content, ephemeral=False)
            sent = True
        except Exception:
            pass

        # Tentative 2 : Via channel.send (si le bot est membre du serveur)
        if not sent:
            try:
                await interaction.channel.send(content=content)
                sent = True
                await interaction.response.send_message(f"✅ Option {opt_num} envoyée dans le salon !", ephemeral=True)
            except discord.Forbidden:
                err_embed = discord.Embed(
                    title="🔒 Permission manquante dans ce salon (403)",
                    description=(
                        "Batman ne peut pas poster directement dans ce salon car :\n"
                        "• Soit le bot n'a pas été **invité sur ce serveur** avec la permission d'écrire (tu l'utilises en tant qu'application utilisateur personnelle).\n"
                        "• Soit il manque la permission **Envoyer des messages** dans ce salon précis.\n\n"
                        "📋 **Copie simplement le texte ci-dessous pour l'envoyer toi-même :**\n"
                        f"```\n{text}\n```"
                    ),
                    color=discord.Color.orange()
                )
                if interaction.response.is_done():
                    await interaction.followup.send(embed=err_embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=err_embed, ephemeral=True)
            except Exception as e:
                err_msg = f"⚠️ Impossible d'envoyer le message : `{e}`"
                if interaction.response.is_done():
                    await interaction.followup.send(err_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(err_msg, ephemeral=True)

    @discord.ui.button(label="Envoyer Option 1", style=discord.ButtonStyle.success, emoji="🎯")
    async def btn_opt1(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._send_reply(interaction, self.opt1, 1)

    @discord.ui.button(label="Envoyer Option 2", style=discord.ButtonStyle.primary, emoji="⚡")
    async def btn_opt2(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._send_reply(interaction, self.opt2, 2)

    @discord.ui.button(label="Envoyer Option 3", style=discord.ButtonStyle.secondary, emoji="🤝")
    async def btn_opt3(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._send_reply(interaction, self.opt3, 3)


@bot.tree.context_menu(name="💬 Répondre à ma place")
@everywhere
async def context_reply_for_me(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content
    if not content:
        return await interaction.response.send_message("❌ Ce message ne contient pas de texte.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    user_style = get_user_style_description(uid)
    style_label = get_user_style_label(uid)

    prompt = f"""Tu es un ghostwriter Discord expert. L'utilisateur veut répondre à ce message reçu de {message.author.display_name} :
« {content} »

Voici le style de langage habituel de l'utilisateur :
{user_style}

Génère 3 propositions de réponses prêtes à l'envoi, adaptées au contexte de la conversation :
1. Dans son style personnel (imitation très fidèle des tics de langage, vocabulaire et ton)
2. Piquante & Drôle (avec de l'esprit, du second degré ou une répartie)
3. Diplomate & Efficace (courte, bienveillante et claire)

RÉPONDS EXACTEMENT AU FORMAT :
===OPT1===
(texte de l'option 1 uniquement)
===OPT2===
(texte de l'option 2 uniquement)
===OPT3===
(texte de l'option 3 uniquement)"""

    try:
        raw = await ask_gemini(prompt)
        opt1, opt2, opt3 = "", "", ""
        if "===OPT1===" in raw and "===OPT2===" in raw and "===OPT3===" in raw:
            parts = raw.split("===OPT1===")[1].split("===OPT2===")
            opt1 = parts[0].strip()
            parts2 = parts[1].split("===OPT3===")
            opt2 = parts2[0].strip()
            opt3 = parts2[1].strip()
        else:
            opt1 = raw[:300].strip()
            opt2 = "Pas mal, mais je préfère passer mon tour !"
            opt3 = "Message bien reçu, je reviens vers toi rapidement !"

        embed = discord.Embed(
            title="💬 Propositions de réponses prêtes à l'emploi",
            description=f"En réponse à **{message.author.display_name}** :\n> *« {content[:150]}... »*\n\n"
                        f"**🎯 Option 1 (Ton style : {style_label}) :**\n```\n{opt1}\n```\n"
                        f"**⚡ Option 2 (Piquante / Drôle) :**\n```\n{opt2}\n```\n"
                        f"**🤝 Option 3 (Diplomate / Bref) :**\n```\n{opt3}\n```",
            color=discord.Color.teal()
        )
        embed.set_footer(text="Discret (visible uniquement par toi) • Clique pour envoyer ou copie directement.")
        view = GhostwriterView(message, interaction.user.id, opt1, opt2, opt3)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# 6. Clic droit sur un message -> Analyser le ton & les sous-entendus
@bot.tree.context_menu(name="🎭 Analyser ton & sous-entendus")
@everywhere
async def context_analyze_tone(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content
    if not content:
        return await interaction.response.send_message("❌ Ce message ne contient pas de texte.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    prompt = f"""Fais une analyse psychologique fine de ce message Discord envoyé par {message.author.display_name} :
« {content} »

Donne :
1. 🎭 **Ton émotionnel dominant** (ex: Passif-agressif, Ironique, Taquin, Flirteur, Sérieux, Énervé, etc.)
2. 🔍 **Sous-entendus & Non-dits** (ce que la personne pense probablement sans le dire ouvertement)
3. 💡 **Conseil stratégique** (comment réagir intelligemment sans créer de drama ou pour reprendre l'avantage)

Reste concis, clair et direct."""

    try:
        analysis = await ask_gemini(prompt)
        embed = discord.Embed(
            title=f"🎭 Analyse de ton : {message.author.display_name}",
            description=f"> *« {content[:200]} »*\n\n{analysis[:1800]}",
            color=discord.Color.purple()
        )
        embed.set_footer(text="Analyse psychologique discrète générée par Batman IA")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


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
# ══════════════════════════════════════════════════════════════
#  ASSISTANT IA GEMINI (MÉMOIRE CONVERSATIONNELLE & VISION)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ia", description="Pose une question à l'IA (avec mémoire continue et vision multimodale)")
@everywhere
@app_commands.describe(
    question="Ta question, consigne ou texte à analyser",
    image="Image optionnelle à envoyer pour analyse (PNG, JPG, WEBP, GIF)"
)
async def ia_command(
    interaction: discord.Interaction,
    question: str,
    image: discord.Attachment = None
):
    await interaction.response.defer(thinking=True)
    try:
        uid = str(interaction.user.id)
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

        # Récupération de l'historique conversationnel (mémoire)
        history = get_user_memory(uid)
        system_prompt = (
            "Tu es Batman, l'assistant ultime de Gotham City. Tu es ultra-intelligent, perspicace, "
            "bienveillant mais doté d'une prestance légendaire. Tu retiens le fil de la discussion "
            "et les informations confiées par l'utilisateur pour lui répondre avec précision en français."
        )

        answer = await ask_gemini(
            prompt=question,
            image_bytes=img_bytes,
            mime_type=mime_type,
            history=history,
            system_instruction=system_prompt
        )

        # Enregistrement dans la mémoire continue de l'utilisateur
        append_user_memory(uid, question, answer)

        if len(answer) > 1900:
            answer = answer[:1900] + "… *(suite tronquée)*"

        embed = discord.Embed(title="🧠 Batman IA", description=answer, color=discord.Color.teal())
        if image is not None:
            embed.set_thumbnail(url=image.url)

        turns = len(get_user_memory(uid)) // 2
        footer = f"Q: {question[:65]} • Mémoire: {turns} échange(s)"
        if image is not None:
            footer += " • 📸 Avec analyse d'image"
        embed.set_footer(text=footer)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`")


class MemoryClearView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="Effacer ma mémoire", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def clear_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.uid:
            return await interaction.response.send_message("❌ Ce n'est pas ton carnet de mémoire.", ephemeral=True)
        reset_user_memory(self.uid)
        button.disabled = True
        await interaction.response.edit_message(
            content="🧹 **Mémoire conversationnelle effacée !** Batman repart sur une feuille blanche.",
            embed=None,
            view=self
        )


@bot.tree.command(name="ia_memoire", description="Consulte ce que l'IA a en mémoire sur vos conversations")
@everywhere
async def ia_memoire(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    hist = get_user_memory(uid)
    style_label = get_user_style_label(uid)
    style_desc = get_user_style_description(uid)

    turns = len(hist) // 2
    embed = discord.Embed(
        title="🧠 Mémoire Conversationnelle de Batman",
        description="Batman garde en mémoire le fil de vos derniers échanges pour des discussions plus fluides et personnalisées.",
        color=discord.Color.teal()
    )
    embed.add_field(name="💬 Échanges retenus", value=f"**{turns}** / 6 conservés", inline=True)
    embed.add_field(name="🎨 Ton profil de style", value=f"**{style_label}**", inline=True)
    embed.add_field(name="📋 Règles actives", value=f"*{style_desc[:250]}*", inline=False)

    if hist:
        last_turn = hist[-2:]
        preview = f"**Toi :** {last_turn[0]['text'][:80]}...\n**Batman :** {last_turn[1]['text'][:80]}..."
        embed.add_field(name="🕒 Dernier échange", value=preview, inline=False)
    else:
        embed.add_field(name="🕒 Dernier échange", value="*Aucun échange récent en mémoire.*", inline=False)

    embed.set_footer(text="Utilise /ia_reset pour effacer ta mémoire à tout moment.")
    view = MemoryClearView(uid) if hist else None
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="ia_reset", description="Efface l'historique conversationnel de l'IA")
@everywhere
async def ia_reset(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    reset_user_memory(uid)
    await interaction.response.send_message("🧹 **Mémoire conversationnelle réinitialisée !**", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  CLONE DE STYLE & RÉPONDRE À MA PLACE (/mon_style & /reponds)
# ══════════════════════════════════════════════════════════════
STYLE_CHOICES = [
    app_commands.Choice(name="🔍 Scanner mes messages du salon (Auto)", value="scan"),
    app_commands.Choice(name="🤙 Familier & Argot urbain", value="familier"),
    app_commands.Choice(name="🤝 Cool & Amical", value="cool"),
    app_commands.Choice(name="💼 Professionnel & Courtois", value="pro"),
    app_commands.Choice(name="🦇 Batman / Sombre & Laconique", value="batman"),
    app_commands.Choice(name="⚡ Sarcastique & Piquant", value="sarcasme"),
    app_commands.Choice(name="✍️ Personnalisé (via description)", value="custom")
]

@bot.tree.command(name="scanner_mon_style", description="Scanne automatiquement tes messages dans le salon pour apprendre ton style")
@everywhere
@app_commands.describe(messages_a_scanner="Nombre de messages à inspecter dans ce salon (ex: 50, 100, 200)")
async def scanner_mon_style(interaction: discord.Interaction, messages_a_scanner: int = 100):
    await interaction.response.defer(thinking=True)
    limit = max(20, min(messages_a_scanner, 250))
    uid = str(interaction.user.id)

    samples = []
    try:
        async for msg in interaction.channel.history(limit=limit):
            if msg.author.id == interaction.user.id:
                txt = msg.clean_content or msg.content
                if txt and len(txt.strip()) > 3 and not txt.startswith(("/", "!", ".")):
                    samples.append(txt.strip())
    except Exception as e:
        return await interaction.followup.send(f"⚠️ Impossible de lire l'historique du salon : `{e}`")

    if len(samples) < 3:
        return await interaction.followup.send(
            f"❌ Je n'ai trouvé que **{len(samples)} message(s)** de toi dans les {limit} derniers messages de ce salon.\n"
            f"Écris quelques messages normaux dans ce salon puis relance, ou augmente la limite (ex: `/scanner_mon_style 200`) !"
        )

    formatted_samples = "\n".join(f"• « {s} »" for s in samples[:35])
    analysis_prompt = (
        f"Tu es un expert linguiste et profileur de style. Voici un échantillon de {len(samples)} messages réels "
        f"écrits par l'utilisateur Discord {interaction.user.display_name} :\n\n{formatted_samples}\n\n"
        "Analyse précisément sa façon de communiquer :\n"
        "- Niveau de langage (argot, familiarité, formalisme, expressions récurrentes)\n"
        "- Ponctuation, majuscules/minuscules et utilisation des emojis\n"
        "- Longueur et structure des phrases\n\n"
        "Rédige une synthèse de 3 règles d'or concrètes pour que l'IA puisse cloner fidèlement ce style."
    )

    try:
        analyzed_rules = await ask_gemini(analysis_prompt)
        set_user_style(uid, "🧠 Profil scanné en direct", analyzed_rules, samples="\n".join(samples[:15]), recent_messages=samples[:25])

        embed = discord.Embed(
            title="🧠 Ton style a été scanné et appris avec succès !",
            description=f"J'ai analysé **{len(samples)} de tes messages** dans ce salon pour comprendre exactement comment tu parles !\n\n"
                        f"**Ce que j'ai appris de ton style :**\n{analyzed_rules}",
            color=discord.Color.green()
        )
        embed.add_field(
            name="💡 Exemples récents retenus",
            value="\n".join(f"> *« {s[:65]}... »*" for s in samples[:3]),
            inline=False
        )
        embed.set_footer(text="Désormais, /reponds_pour_moi et le clic-droit imitent automatiquement tes vraies habitudes !")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur lors de l'analyse IA : `{e}`")

@bot.tree.command(name="mon_style", description="Configure ou fais analyser ton style d'écriture par l'IA")
@everywhere
@app_commands.describe(
    preset="Choisis un profil préconfiguré ou Personnalisé",
    description="Exemples de tes messages ou description de ta façon de parler (pour 'Personnalisé')"
)
@app_commands.choices(preset=STYLE_CHOICES)
async def mon_style(
    interaction: discord.Interaction,
    preset: app_commands.Choice[str],
    description: str = None
):
    uid = str(interaction.user.id)
    chosen_key = preset.value

    if chosen_key == "scan":
        return await scanner_mon_style.callback(interaction, 100)

    if chosen_key in PRESET_STYLES and not description:
        info = PRESET_STYLES[chosen_key]
        set_user_style(uid, info["label"], info["rules"], "")
        embed = discord.Embed(
            title="🎨 Style de langage mis à jour !",
            description=f"Profil activé : **{info['label']}**\n\n> *« {info['rules']} »*",
            color=discord.Color.green()
        )
        embed.set_footer(text="Ce style sera automatiquement utilisé par /reponds_pour_moi et le clic-droit.")
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    if not description:
        return await interaction.response.send_message(
            "❌ Pour un profil personnalisé, colle quelques exemples de tes messages habituels dans le champ `description` !",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        analysis_prompt = (
            f"Analyse ces messages/description fournis par un utilisateur Discord :\n"
            f"« {description} »\n\n"
            f"Extrais en 2 phrases précises les règles de son style : niveau de langage, tutoiement/vouvoiement, "
            f"ponctuation, expressions récurrentes, longueur moyenne et utilisation d'emojis."
        )
        analyzed_rules = await ask_gemini(analysis_prompt)
        set_user_style(uid, "✍️ Personnalisé", analyzed_rules, description[:300])

        embed = discord.Embed(
            title="🧬 Profil de langage analysé avec succès !",
            description=f"**Règles déduites par l'IA :**\n{analyzed_rules}\n\n"
                        f"**Exemples analysés :**\n> *« {description[:180]} »*",
            color=discord.Color.teal()
        )
        embed.set_footer(text="Batman utilisera cette empreinte pour générer des réponses en ton nom.")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur lors de l'analyse : `{e}`", ephemeral=True)


REPLY_INTENTIONS = [
    app_commands.Choice(name="🎯 Naturel (selon mon style)", value="Répondre de façon naturelle"),
    app_commands.Choice(name="👍 Accepter avec enthousiasme", value="Accepter avec enthousiasme"),
    app_commands.Choice(name="🙅 Refuser poliment mais fermement", value="Refuser poliment mais fermement"),
    app_commands.Choice(name="⏳ Reporter / Gagner du temps", value="Reporter à plus tard avec tact"),
    app_commands.Choice(name="⚡ Répartie piquante / Humour", value="Répondre avec humour piquant et répartie"),
    app_commands.Choice(name="💼 Professionnel & Neutre", value="Réponse professionnelle, carrée et neutre")
]

@bot.tree.command(name="reponds_pour_moi", description="Génère 3 réponses parfaites calibrées sur ton style d'écriture")
@everywhere
@app_commands.describe(
    message="Ce qu'on t'a dit ou le message auquel tu veux répondre",
    intention="Quelle est ton intention pour cette réponse ?"
)
@app_commands.choices(intention=REPLY_INTENTIONS)
async def reponds_pour_moi(
    interaction: discord.Interaction,
    message: str,
    intention: app_commands.Choice[str] = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    user_style = get_user_style_description(uid)
    style_label = get_user_style_label(uid)
    intent_text = intention.value if intention else "Répondre de façon naturelle et percutante"

    prompt = f"""Tu es un ghostwriter Discord d'élite. L'utilisateur veut répondre à ce message :
« {message} »

Intention souhaitée : {intent_text}
Style habituel de l'utilisateur :
{user_style}

Génère exactement 3 options de réponses prêtes à l'envoi :
1. Dans son style personnel (respectant scrupuleusement ses habitudes de langage)
2. Piquante / Pleine d'esprit (avec du second degré ou une répartie)
3. Diplomate & Efficace (courte et sans ambiguïté)

FORMAT EXACT :
===OPT1===
(texte option 1)
===OPT2===
(texte option 2)
===OPT3===
(texte option 3)"""

    try:
        raw = await ask_gemini(prompt)
        opt1, opt2, opt3 = "", "", ""
        if "===OPT1===" in raw and "===OPT2===" in raw and "===OPT3===" in raw:
            parts = raw.split("===OPT1===")[1].split("===OPT2===")
            opt1 = parts[0].strip()
            parts2 = parts[1].split("===OPT3===")
            opt2 = parts2[0].strip()
            opt3 = parts2[1].strip()
        else:
            opt1 = raw[:300].strip()
            opt2 = "Pas mal, mais je préfère passer mon tour !"
            opt3 = "Message bien reçu, je reviens vers toi rapidement !"

        embed = discord.Embed(
            title="💬 Réponses prêtes à l'emploi générées",
            description=f"**Message reçu :**\n> *« {message[:160]} »*\n\n"
                        f"**🎯 Option 1 (Ton style : {style_label}) :**\n```\n{opt1}\n```\n"
                        f"**⚡ Option 2 (Piquante / Drôle) :**\n```\n{opt2}\n```\n"
                        f"**🤝 Option 3 (Diplomate / Bref) :**\n```\n{opt3}\n```",
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"Intention : {intent_text} • Copie l'option de ton choix !")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  OUTILS DE CONVERSATION : REFORMULATION & RÉPARTIES
# ══════════════════════════════════════════════════════════════
REFORMULER_STYLES = [
    app_commands.Choice(name="💼 Professionnel & Poli", value="Professionnel, courtois, soutenu et sans fautes"),
    app_commands.Choice(name="⚡ Clash percutant & sans pitié", value="Cinglant, tranchant, répartie affûtée sans insultes"),
    app_commands.Choice(name="🦇 Batman / Dark Knight", value="Sombre, laconique, percutant et mystérieux"),
    app_commands.Choice(name="🤝 Diplomate & Apaisant", value="Diplomatique, bienveillant, apaisant et mesuré"),
    app_commands.Choice(name="😂 Humoristique & Second degré", value="Drôle, auto-dérision, second degré et plein d'esprit"),
    app_commands.Choice(name="✨ Éloquent & Poétique", value="Vocabulaire riche, poétique, soigné et littéraire"),
    app_commands.Choice(name="📏 Minimaliste & Direct", value="Ultra court, sans fioriture, direct au but"),
    app_commands.Choice(name="🔤 Corriger l'orthographe & style", value="Corrige la grammaire, la syntaxe et l'orthographe en restant naturel")
]

@bot.tree.command(name="reformuler", description="Reformule un texte ou un brouillon dans le style de ton choix")
@everywhere
@app_commands.describe(
    texte="Le texte ou brouillon à reformuler",
    style="Le style d'écriture souhaité"
)
@app_commands.choices(style=REFORMULER_STYLES)
async def reformuler(
    interaction: discord.Interaction,
    texte: str,
    style: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    prompt = (
        f"Reformule le texte suivant dans ce style : « {style.value} ».\n"
        f"Conserve l'idée d'origine mais maximise l'impact du message.\n"
        f"Ne donne QUE le texte final réécrit, sans intro ni commentaires :\n\n{texte}"
    )
    try:
        result = await ask_gemini(prompt)
        embed = discord.Embed(
            title=f"✍️ Reformulation ({style.name})",
            description=f"**Original :**\n> *« {texte} »*\n\n**Résultat :**\n```\n{result[:1800]}\n```",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Visible uniquement par toi • Prêt à copier !")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur : `{e}`", ephemeral=True)


@bot.tree.command(name="repartie", description="Génère des réparties et punchlines mémorables")
@everywhere
@app_commands.describe(
    sujet="La pique reçue, le sujet ou ce qu'on vient de te dire",
    intensite="Niveau d'intensité de la répartie"
)
@app_commands.choices(intensite=[
    app_commands.Choice(name="😄 Taquin & Bon enfant", value="taquin"),
    app_commands.Choice(name="🔥 Piquant & Mordant", value="piquant"),
    app_commands.Choice(name="⚡ Clash destructeur (sans vulgarité)", value="clash"),
    app_commands.Choice(name="🦇 Punchline Batman", value="batman")
])
async def repartie(
    interaction: discord.Interaction,
    sujet: str,
    intensite: app_commands.Choice[str] = None
):
    await interaction.response.defer(thinking=True)
    lvl = intensite.value if intensite else "piquant"
    prompt = (
        f"Génère 3 réparties ou punchlines cinglantes, spirituelles et intelligentes (sans insultes) "
        f"pour répliquer à cette phrase ou situation : « {sujet} ».\n"
        f"Niveau d'intensité : {lvl}.\n"
        f"Présente-les en 3 puces numérotées bien espacées avec des emojis adaptés."
    )
    try:
        res = await ask_gemini(prompt)
        embed = discord.Embed(
            title="⚡ Réparties & Punchlines IA",
            description=f"**En réponse à :**\n> *« {sujet[:150]} »*\n\n{res[:1800]}",
            color=discord.Color.dark_red()
        )
        embed.set_footer(text="Fourni par Batman • À utiliser avec modération 😉")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur : `{e}`")


# ══════════════════════════════════════════════════════════════
#  MODE ABSENCE INTELLIGENT (/afk & /afk_off)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="afk", description="Active ton mode absence (Batman prévient ceux qui te mentionnent)")
@everywhere
@app_commands.describe(raison="La raison de ton absence (ex: repas, dodo, révisions, sport...)")
async def afk(interaction: discord.Interaction, raison: str = "Absent pour le moment"):
    uid = str(interaction.user.id)
    afk_data = load_json(AFK_FILE)
    afk_data[uid] = {
        "reason": raison,
        "since": int(datetime.now().timestamp())
    }
    save_json(AFK_FILE, afk_data)
    embed = discord.Embed(
        title="💤 Mode AFK activé",
        description=f"**{interaction.user.display_name}**, je préviendrai automatiquement toute personne qui te mentionne !\n\n"
                    f"**Raison :** *« {raison} »*",
        color=discord.Color.dark_grey()
    )
    embed.set_footer(text="Ton mode AFK s'enlèvera automatiquement dès que tu renverras un message.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="afk_off", description="Désactive manuellement ton mode absence")
@everywhere
async def afk_off(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    afk_data = load_json(AFK_FILE)
    if uid in afk_data:
        del afk_data[uid]
        save_json(AFK_FILE, afk_data)
        await interaction.response.send_message("✅ Ton mode AFK a été désactivé !", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ Tu n'étais pas en mode AFK.", ephemeral=True)


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

IMAGE_RATIOS = [
    app_commands.Choice(name="⬛ Carré 1:1 (Avatar / Insta)", value="1:1"),
    app_commands.Choice(name="🖥️ Paysage 16:9 (Fond d'écran)", value="16:9"),
    app_commands.Choice(name="📱 Portrait 9:16 (Story / Phone)", value="9:16"),
    app_commands.Choice(name="📐 Standard 4:3", value="4:3"),
    app_commands.Choice(name="📜 Vertical 3:4", value="3:4")
]

class GeneratedImageView(discord.ui.View):
    def __init__(self, author_id: int, prompt: str, style_value: str, style_label: str, aspect_ratio: str = "1:1"):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.prompt = prompt
        self.style_value = style_value
        self.style_label = style_label
        self.aspect_ratio = aspect_ratio

    @discord.ui.button(label="Régénérer", style=discord.ButtonStyle.primary, emoji="🔄")
    async def regenerate_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Seul l'auteur de la demande peut régénérer cette image.", ephemeral=True)
        await interaction.response.defer()
        try:
            img_bytes, engine = await generate_ai_image(self.prompt, self.style_value, self.aspect_ratio)
            file = discord.File(io.BytesIO(img_bytes), filename="batman_art.png")
            embed = discord.Embed(
                title="🎨 Image générée par l'IA",
                description=f"**Prompt :** {self.prompt}\n**Style :** {self.style_label}\n**Format :** `{self.aspect_ratio}`",
                color=discord.Color.dark_theme()
            )
            embed.set_image(url="attachment://batman_art.png")
            embed.set_footer(text=f"Régénéré par {interaction.user.display_name} • Moteur : {engine}")
            await interaction.message.edit(embed=embed, attachments=[file], view=self)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur lors de la régénération : `{e}`", ephemeral=True)

    @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Tu ne peux pas supprimer l'image d'un autre membre.", ephemeral=True)
        await interaction.message.delete()


@bot.tree.command(name="image", description="Génère une image originale par intelligence artificielle")
@everywhere
@app_commands.describe(
    description="Ce que tu veux voir sur l'image (ex: Batman contemplant Gotham sous la pluie)",
    style="Style artistique optionnel pour l'image",
    format="Format ou ratio de l'image (Carré 1:1, Paysage 16:9, Portrait 9:16...)"
)
@app_commands.choices(style=IMAGE_STYLES, format=IMAGE_RATIOS)
async def image_command(
    interaction: discord.Interaction,
    description: str,
    style: app_commands.Choice[str] = None,
    format: app_commands.Choice[str] = None
):
    await interaction.response.defer(thinking=True)
    try:
        chosen_style = style.value if style else "Naturel"
        style_label = style.name if style else "Standard"
        chosen_ratio = format.value if format else "1:1"
        img_bytes, engine = await generate_ai_image(description, chosen_style, chosen_ratio)

        file = discord.File(io.BytesIO(img_bytes), filename="batman_art.png")
        embed = discord.Embed(
            title="🎨 Image générée par l'IA",
            description=f"**Prompt :** {description}\n**Style :** {style_label}\n**Format :** `{chosen_ratio}`",
            color=discord.Color.dark_theme()
        )
        embed.set_image(url="attachment://batman_art.png")
        embed.set_footer(text=f"Demandé par {interaction.user.display_name} • Moteur : {engine}")
        view = GeneratedImageView(interaction.user.id, description, chosen_style, style_label, chosen_ratio)
        await interaction.followup.send(embed=embed, file=file, view=view)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur lors de la génération de l'image : `{e}`")


@bot.tree.command(name="imagine", description="Génère une image artistique par IA (alias de /image)")
@everywhere
@app_commands.describe(prompt="Description de l'image à imaginer")
async def imagine_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer(thinking=True)
    try:
        img_bytes, engine = await generate_ai_image(prompt, "Naturel", "1:1")
        file = discord.File(io.BytesIO(img_bytes), filename="imagine_art.png")
        embed = discord.Embed(
            title="✨ Imagination IA",
            description=f"> {prompt}",
            color=discord.Color.purple()
        )
        embed.set_image(url="attachment://imagine_art.png")
        embed.set_footer(text=f"Demandé par {interaction.user.display_name} • Moteur : {engine}")
        view = GeneratedImageView(interaction.user.id, prompt, "Naturel", "Standard", "1:1")
        await interaction.followup.send(embed=embed, file=file, view=view)
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
