import os
import json
import asyncio
import re
import random
from datetime import datetime, timezone
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ─────────────────────────── CONFIG ───────────────────────────
load_dotenv()

TOKEN      = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PORT       = int(os.getenv("PORT", "8080"))

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
NOTES_FILE  = os.path.join(DATA_DIR, "notes.json")
TODOS_FILE  = os.path.join(DATA_DIR, "todos.json")
TIMER_FILE  = os.path.join(DATA_DIR, "timers.json")

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

# ─────────────────────── ON READY ─────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Connected as {bot.user} ({bot.user.id})", flush=True)
    try:
        synced = await bot.tree.sync()
        print(f"⚡ {len(synced)} slash commands synced.", flush=True)
    except Exception as e:
        print(f"⚠️ Sync error: {e}", flush=True)
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="/aide | 🦇 Partout avec toi"
    ))

# ══════════════════════════════════════════════════════════════
#  DÉCORATIONS COMMUNES (disponibles partout : serveurs + MP)
# ══════════════════════════════════════════════════════════════
def everywhere(cmd):
    cmd = app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(cmd)
    cmd = app_commands.allowed_installs(guilds=True, users=True)(cmd)
    return cmd

# ══════════════════════════════════════════════════════════════
#  /aide  —  Menu d'aide complet avec pagination boutons
# ══════════════════════════════════════════════════════════════
HELP_PAGES = [
    {
        "title": "🦇 Batman — Page 1 / 4 : Essentiels",
        "color": discord.Color.dark_theme(),
        "fields": [
            ("🏓 /ping", "Teste la réactivité du bot et affiche la latence.", False),
            ("⏰ /rappel", "`duree` + `message` — Programme un rappel (10m, 2h, 1j…). Reçois la notification en MP !", False),
            ("📊 /stats", "Affiche un résumé de tes activités (tâches, notes, rappels).", False),
            ("🎲 /dice", "`faces` — Lance un dé à N faces. Fun & jeux de rôle.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 2 / 4 : To-Do Interactive",
        "color": discord.Color.blue(),
        "fields": [
            ("✅ /todo", "Tableau de bord interactif : coche d'un clic, ajoute via pop-up, actualise !", False),
            ("➕ /todo_ajouter", "`tache` — Ajout rapide sans ouvrir le tableau.", False),
            ("🗑️ /todo_terminer", "`numero` — Supprime une tâche par son numéro.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 3 / 4 : Notes & Chrono",
        "color": discord.Color.purple(),
        "fields": [
            ("📝 /note", "Tableau de bord interactif pour tes notes : lire, ajouter, supprimer.", False),
            ("📌 /note_ajouter", "`titre` + `contenu` — Sauvegarde rapide d'une idée.", False),
            ("⏱️ /chrono", "`duree` + `nom` — Lance un chrono Pomodoro. Alerte à la fin !", False),
            ("🔄 /rappel_quotidien", "`heure` + `message` — Rappel qui se répète chaque jour à l'heure choisie.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 4 / 4 : IA & Outils",
        "color": discord.Color.teal(),
        "fields": [
            ("🧠 /ia", "`question` — Demande à Gemini 2.5 Flash de résumer, traduire, brainstormer…", False),
            ("🌤️ /meteo", "`ville` — Météo actuelle de n'importe quelle ville du monde.", False),
            ("🔗 /resume", "`url` — Résume automatiquement une page web ou un article.", False),
            ("📈 /calcul", "`expression` — Calculatrice avancée (avec exposants, parenthèses…)", False),
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
        embed.set_footer(text=f"Page {self.page + 1}/{len(HELP_PAGES)} • Hébergé H24 sur Render")
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
#  /ping
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ping", description="Vérifie la réactivité du bot")
@everywhere
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    color = discord.Color.green() if latency < 150 else discord.Color.orange()
    embed = discord.Embed(
        title="🏓 Pong !",
        description=f"**Latence :** `{latency} ms`\n**Statut :** {'🟢 Excellent' if latency < 150 else '🟡 Correct'}",
        color=color
    )
    uptime = int((datetime.now(timezone.utc) - start_time).total_seconds())
    h, r = divmod(uptime, 3600); m, s = divmod(r, 60)
    embed.add_field(name="⏳ Uptime", value=f"`{h}h {m}m {s}s`")
    await interaction.response.send_message(embed=embed)


# ══════════════════════════════════════════════════════════════
#  /rappel  —  Timer one-shot avec livraison en MP
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
@bot.tree.command(name="chrono", description="Lance un chrono Pomodoro (alerte en MP à la fin)")
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
            description=f"**{nom}** est terminé(e) ! Bien joué 🎉\nPense à faire une petite pause.",
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
#  /dice  —  Dé à N faces
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
#  /calcul  —  Calculatrice sécurisée
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="calcul", description="Calculatrice avancée")
@everywhere
@app_commands.describe(expression="Ex : (3+5)*2, 2**10, sqrt(144)")
async def calcul(interaction: discord.Interaction, expression: str):
    import math
    allowed = set("0123456789+-*/().%, eE")
    safe_funcs = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    safe_funcs["abs"] = abs; safe_funcs["round"] = round
    clean = expression.replace("^", "**").replace(",", ".")
    if any(c not in allowed and not c.isalpha() for c in clean):
        return await interaction.response.send_message("❌ Expression non sécurisée.", ephemeral=True)
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
#  /meteo  —  Météo via Open-Meteo (sans clé API !)
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="meteo", description="Météo actuelle de n'importe quelle ville")
@everywhere
@app_commands.describe(ville="Nom de la ville (ex: Paris, Tokyo, Alger…)")
async def meteo(interaction: discord.Interaction, ville: str):
    await interaction.response.defer(thinking=True)
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Géocodage
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={ville}&count=1&language=fr"
            async with session.get(geo_url) as r:
                geo = await r.json()
            if not geo.get("results"):
                return await interaction.followup.send(f"❌ Ville introuvable : **{ville}**", ephemeral=True)
            loc = geo["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            city_name = loc.get("name", ville)
            country   = loc.get("country", "")
            # 2. Météo
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
                0:"☀️ Ciel dégagé", 1:"🌤️ Mostly clear", 2:"⛅ Partly cloudy", 3:"☁️ Couvert",
                45:"🌫️ Brouillard", 48:"🌫️ Brouillard glacé",
                51:"🌦️ Bruine légère", 53:"🌦️ Bruine", 55:"🌧️ Bruine dense",
                61:"🌧️ Pluie légère", 63:"🌧️ Pluie", 65:"🌧️ Pluie forte",
                71:"🌨️ Neige légère", 73:"❄️ Neige", 75:"❄️ Neige forte",
                80:"🌧️ Averses", 81:"🌧️ Averses fortes", 82:"⛈️ Averses violentes",
                95:"⛈️ Orage", 96:"⛈️ Orage avec grêle", 99:"⛈️ Orage violent"
            }
            desc = ICONS.get(code, f"Code {code}")
            embed = discord.Embed(
                title=f"🌍 Météo — {city_name}, {country}",
                description=f"**{desc}**",
                color=discord.Color.from_rgb(100, 180, 255)
            )
            embed.add_field(name="🌡️ Température", value=f"`{cur['temperature_2m']}°C`")
            embed.add_field(name="🤔 Ressentie", value=f"`{cur['apparent_temperature']}°C`")
            embed.add_field(name="💧 Humidité", value=f"`{cur['relativehumidity_2m']}%`")
            embed.add_field(name="💨 Vent", value=f"`{cur['windspeed_10m']} km/h`")
            embed.set_footer(text="Source : Open-Meteo • Données temps réel")
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur météo : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /stats  —  Résumé de tes données
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
#  /todo  —  Tableau de bord interactif avec boutons et menus
# ══════════════════════════════════════════════════════════════
def create_todo_embed(user_name: str, tasks: list) -> discord.Embed:
    embed = discord.Embed(title=f"📋 To-Do — {user_name}", color=discord.Color.blue())
    if not tasks:
        embed.description = "🎉 **Aucune tâche !**\nClique sur **➕ Ajouter** pour en créer une."
    else:
        lines = [f"`{i}.` {t['task']} *(le {t.get('date','')})*"
                 for i, t in enumerate(tasks, 1)]
        embed.description = "\n".join(lines)
        embed.set_footer(text="Sélectionne une tâche dans le menu pour la cocher ✅")
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

@bot.tree.command(name="todo_terminer", description="Supprime une tâche par son numéro")
@everywhere
@app_commands.describe(numero="Numéro de la tâche")
async def todo_terminer(interaction: discord.Interaction, numero: int):
    uid = str(interaction.user.id)
    todos = load_json(TODOS_FILE)
    lst = todos.get(uid, [])
    if not lst or numero < 1 or numero > len(lst):
        return await interaction.response.send_message("❌ Numéro invalide.", ephemeral=True)
    done = lst.pop(numero - 1)
    todos[uid] = lst; save_json(TODOS_FILE, todos)
    await interaction.response.send_message(f"🎉 Terminée : ~~{done['task']}~~", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  /note  —  Notes interactives avec boutons
# ══════════════════════════════════════════════════════════════
def create_notes_embed(user_name: str, notes: list) -> discord.Embed:
    embed = discord.Embed(title=f"📚 Notes — {user_name}", color=discord.Color.purple())
    if not notes:
        embed.description = "📭 Aucune note.\nClique sur **➕ Nouvelle note** pour commencer."
    else:
        for n in notes[-8:]:
            embed.add_field(
                name=f"📌 {n['title']} ({n.get('date', '')})",
                value=n['content'][:200] + ("…" if len(n['content']) > 200 else ""),
                inline=False
            )
        embed.set_footer(text=f"{len(notes)} note(s) au total • /note pour tout voir")
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
#  /ia  —  Assistant IA Gemini
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="ia", description="Pose une question à l'IA (Gemini 2.5 Flash)")
@everywhere
@app_commands.describe(question="Ta question, texte à résumer ou consigne")
async def ia_command(interaction: discord.Interaction, question: str):
    if not GEMINI_KEY:
        return await interaction.response.send_message(
            "💡 Active l'IA en ajoutant `GEMINI_API_KEY` sur Render.\n"
            "Clé gratuite : https://aistudio.google.com/app/apikey", ephemeral=True)
    await interaction.response.defer(thinking=True)
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_KEY)
        resp = client.models.generate_content(model="gemini-3.8-flash", contents=question)
        answer = (resp.text or "Pas de réponse.")[:1900]
        embed = discord.Embed(title="🧠 Réponse IA", description=answer, color=discord.Color.teal())
        embed.set_footer(text=f"Q: {question[:90]}")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ `{e}`")


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
