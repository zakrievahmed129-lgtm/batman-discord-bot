import os
import json
import asyncio
import re
import random
import math
import io
import urllib.parse
from datetime import datetime, timezone, timedelta
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

    # 3. Apprentissage automatique discret du style & de l'humour de l'auteur
    content = message.clean_content or message.content
    if content and record_user_writing(uid, content, is_chat=True):
        maybe_schedule_humor_dna(uid)

    # 4. Discussion naturelle en Message Privé (MP avec Batman) ou par mention (@Batman)
    is_dm = message.guild is None
    is_mentioned = (bot.user in message.mentions) if bot.user else False

    if (is_dm or is_mentioned) and (content or message.attachments) and not (content or "").startswith(("/", "!", ".")):
        clean_text = content or ""
        if is_mentioned and bot.user:
            clean_text = clean_text.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

        file_bytes = None
        mime = "image/png"
        extra_file_text = None
        kind_label = None
        if message.attachments:
            try:
                file_bytes, mime, extra_file_text, kind_label = await extract_attachment_payload(message.attachments[0])
            except Exception:
                pass

        # Calibrage naturel en MP : si l'utilisateur décrit son humour ou envoie un screen de ses messages
        lower_t = clean_text.lower()
        calibration_triggers = (
            "apprends mon humour", "mon humour c'est", "mon humour est", "voici mon humour",
            "voila mon humour", "voilà mon humour", "imite mon humour", "copie mon humour",
            "apprends mon style", "voici mon style", "voila mon style", "voilà mon style",
            "imite mon style", "copie mon style", "voici comment je parle", "voila comment je parle",
            "voilà comment je parle", "calibre mon humour"
        )
        if is_dm and any(trig in lower_t for trig in calibration_triggers):
            try:
                async with message.channel.typing():
                    dna = await analyze_and_save_humor_dna(
                        uid=uid,
                        explicit_notes=clean_text,
                        extra_image_bytes=file_bytes if (file_bytes and kind_label and "Image" in kind_label) else None,
                        extra_mime=mime or "image/png"
                    )
                    if dna:
                        await message.reply(
                            f"✅ C'est noté et mémorisé pour `💬 Répondre à ma place`, `/reformuler` et `/repartie` :\n\n{dna[:1600]}"
                        )
                    else:
                        await message.reply("✅ J'ai bien enregistré ton style et ton humour !")
                    return
            except Exception:
                pass

        if not clean_text and (file_bytes or extra_file_text):
            if kind_label and "Vocal" in kind_label:
                clean_text = "Écoute ce message vocal, transcris l'essentiel et réponds-moi ou résume-le clairement."
            elif kind_label and "Image" in kind_label:
                clean_text = "Analyse cette image en détail (s'il y a un exercice, du texte ou une question dessus, résous-le ou explique-le)."
            else:
                clean_text = "Analyse et résume clairement le contenu de ce document."

        if extra_file_text:
            clean_text = f"{clean_text}\n\n--- CONTENU DU FICHIER JOINT ---\n{extra_file_text}"

        if clean_text:
            try:
                async with message.channel.typing():
                    history = get_user_memory(uid)
                    system_prompt = (
                        f"Tu es Batman, l'assistant personnel loyal et ultra-intelligent de {message.author.display_name}. "
                        "Tu t'exprimes avec assurance, clarté et efficacité : direct, pertinent, toujours prêt à résoudre "
                        "un problème, vérifier une info en direct ou analyser un fichier/vocal/image."
                    )
                    reply_text = await ask_gemini(
                        prompt=clean_text,
                        image_bytes=file_bytes,
                        mime_type=mime or "image/png",
                        history=history,
                        system_instruction=system_prompt,
                        use_search=(file_bytes is None)
                    )
                    append_user_memory(uid, clean_text[:600], reply_text)

                    if len(reply_text) <= 2000:
                        await message.reply(reply_text)
                    else:
                        for chunk in [reply_text[i:i+1950] for i in range(0, len(reply_text), 1950)]:
                            await message.channel.send(chunk)
                    return
            except Exception as e:
                try:
                    await message.reply(f"🦇 *(Batman)* Une interférence radio a perturbé ma liaison : `{e}`")
                except Exception:
                    pass
                return

    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════
#  DÉCORATIONS COMMUNES (disponibles partout : serveurs + MP)
# ══════════════════════════════════════════════════════════════
def everywhere(cmd):
    cmd = app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)(cmd)
    cmd = app_commands.allowed_installs(guilds=True, users=True)(cmd)
    return cmd

# ══════════════════════════════════════════════════════════════
#  HELPERS IA : GEMINI (VISION, VOCAUX, PDF, RECHERCHE WEB) + MÉMOIRE
# ══════════════════════════════════════════════════════════════
async def extract_attachment_payload(att: discord.Attachment):
    """Extrait (bytes_data, mime_type, text_content, kind_label) d'une pièce jointe Discord (image, vocal, PDF, texte/code)."""
    ct = (att.content_type or "").split(";")[0].strip().lower()
    fn = att.filename.lower()

    if ct.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        data = await att.read()
        mime = ct if ct.startswith("image/") else ("image/jpeg" if fn.endswith((".jpg", ".jpeg")) else "image/png")
        return data, mime, None, "📸 Image"

    if ct.startswith("audio/") or fn.endswith((".ogg", ".mp3", ".wav", ".m4a", ".opus", ".aac", ".webm")):
        data = await att.read()
        mime = ct if ct.startswith("audio/") else (
            "audio/ogg" if fn.endswith((".ogg", ".opus")) else
            "audio/mpeg" if fn.endswith(".mp3") else
            "audio/mp4" if fn.endswith(".m4a") else "audio/wav"
        )
        return data, mime, None, "🎙️ Message vocal / Audio"

    if ct == "application/pdf" or fn.endswith(".pdf"):
        data = await att.read()
        return data, "application/pdf", None, "📄 Document PDF"

    if ct.startswith("text/") or fn.endswith((".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css", ".lua", ".sql", ".xml", ".yaml", ".yml", ".log")):
        raw = await att.read()
        txt = raw.decode("utf-8", errors="replace")[:15000]
        return None, None, txt, f"📝 Fichier ({att.filename})"

    return None, None, None, None


async def ask_gemini(
    prompt: str,
    image_bytes: bytes = None,
    mime_type: str = "image/png",
    history: list = None,
    system_instruction: str = None,
    use_search: bool = False
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

    # 2. Tour actuel (texte + média optionnel : image, audio/vocal, PDF)
    user_parts = []
    if image_bytes:
        clean_mime = mime_type.split(";")[0].strip() if mime_type else "image/png"
        user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type=clean_mime))
    user_parts.append(types.Part.from_text(text=prompt))
    contents.append(types.Content(role="user", parts=user_parts))

    base_config = types.GenerateContentConfig(system_instruction=system_instruction) if system_instruction else None
    search_config = None
    if use_search and not image_bytes:
        try:
            cfg_kwargs = {"tools": [types.Tool(google_search=types.GoogleSearch())]}
            if system_instruction:
                cfg_kwargs["system_instruction"] = system_instruction
            search_config = types.GenerateContentConfig(**cfg_kwargs)
        except Exception:
            search_config = None

    last_err = None
    for m in models:
        if search_config is not None:
            try:
                resp = await client.aio.models.generate_content(model=m, contents=contents, config=search_config)
                if resp.text:
                    return resp.text.strip()
            except Exception as e:
                last_err = e
        try:
            resp = await client.aio.models.generate_content(model=m, contents=contents, config=base_config)
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


# ─────────────── GESTION DU STYLE, HUMOUR & ANTI-IA ─────────────
OLD_DEFAULT_STYLE = "Naturel, décontracté, tutoiement amical, phrases claires, emojis légers"
DEFAULT_STYLE = (
    "100% humain façon vrai message Discord/SMS : zéro emoji, zéro smiley, minuscules naturelles, "
    "pas de ponctuation scolaire ni de point final rigide, messages courts et directs, "
    "humour second degré / pince-sans-rire / taquin naturel sans jamais forcer ni sonner comme une IA"
)

_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\u2600-\u27BF"
    "\u231A-\u231B"
    "\u23E9-\u23FA"
    "\u25AA-\u25FE"
    "\u2934-\u2935"
    "\u2B05-\u2B55"
    "\u203C\u2049\u2139\u2194-\u21AA\u24C2"
    "\uFE0E\uFE0F\u200D\u20E3"
    "]+",
    flags=re.UNICODE
)
_EMOTICON_RE = re.compile(r"(?<!\S)(?:[:;][-']?[)D(PpOo]|<3|\^\^)(?!\S)")

def strip_emojis(text: str) -> str:
    if not text:
        return ""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = _EMOTICON_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def clean_human_discord_reply(text: str, allow_emojis: bool = False, strip_trailing_dot: bool = True) -> str:
    if not text:
        return ""
    s = text.strip().replace("```", "").strip("`«»\"")
    s = re.sub(r"^(?:option\s*\d+|réponse\s*\d+|r\d+)\s*[:\-–]\s*", "", s, flags=re.IGNORECASE).strip()
    s = s.strip("«»\"")
    if not allow_emojis:
        s = strip_emojis(s)
    # Remplace les tirets cadratins trop "IA" par un espacement simple si besoin
    s = s.replace(" — ", " - ").replace("—", "-")
    if strip_trailing_dot and s.endswith(".") and not s.endswith(("..", "...")):
        # Garde le point seulement s'il y a plusieurs phrases ou si c'est long
        if len(s) < 130 and s.count(".") == 1:
            s = s[:-1].rstrip()
    return s.strip()

PRESET_STYLES = {
    "familier": {
        "label": "Familier & Discord",
        "rules": "Naturel, langage courant/familier crédible, phrases courtes, minuscules, direct, détendu, zéro emoji."
    },
    "cool": {
        "label": "Naturel & Posé",
        "rules": "Décontracté, tutoiement spontané, simple, posé, zéro emoji et zéro phrase robotique."
    },
    "pro": {
        "label": "Pro & Poli",
        "rules": "Poli, soigné, sans fautes, courtois, clair, sans emojis."
    },
    "batman": {
        "label": "Batman / Laconique",
        "rules": "Sombre, laconique, froid et percutant, aucune fioriture, zéro emoji."
    },
    "sarcasme": {
        "label": "Pince-sans-rire & Second degré",
        "rules": "Humour sec, second degré pince-sans-rire, taquin et incisif sans lourdeur ni emojis."
    }
}

_humor_tasks_inflight: set[str] = set()

def record_user_writing(uid: str, text: str, is_chat: bool = True) -> bool:
    """Enregistre discrètement un vrai message ou brouillon de l'utilisateur pour imiter son humour et son ton."""
    if not text:
        return False
    clean = text.strip()
    if len(clean) < 3 or len(clean) > 220 or clean.startswith(("/", "!", ".")):
        return False
    if clean.startswith(("http://", "https://")) and " " not in clean:
        return False
    try:
        styles = load_json(STYLES_FILE)
        u_style = styles.get(uid, {
            "label": "Apprentissage auto",
            "rules": DEFAULT_STYLE,
            "recent_messages": [],
            "intent_hints": []
        })
        if u_style.get("rules") == OLD_DEFAULT_STYLE:
            u_style["rules"] = DEFAULT_STYLE
        field = "recent_messages" if is_chat else "intent_hints"
        limit = 35 if is_chat else 15
        lst = u_style.get(field, [])
        if clean not in lst:
            lst.append(clean)
            u_style[field] = lst[-limit:]
            u_style["updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
            styles[uid] = u_style
            save_json(STYLES_FILE, styles)
            return True
    except Exception:
        pass
    return False

async def analyze_and_save_humor_dna(
    uid: str,
    explicit_notes: str = None,
    explicit_examples: list[str] = None,
    extra_image_bytes: bytes = None,
    extra_mime: str = "image/png"
) -> str:
    """Analyse automatiquement les messages/exemples pour extraire l'ADN exact d'humour et d'écriture de l'utilisateur."""
    _humor_tasks_inflight.add(uid)
    try:
        styles = load_json(STYLES_FILE)
        u_style = styles.get(uid, {
            "label": "Apprentissage auto",
            "rules": DEFAULT_STYLE,
            "recent_messages": [],
            "intent_hints": []
        })
        if explicit_notes is not None and explicit_notes.strip():
            u_style["humor_notes"] = explicit_notes.strip()[:400]
            u_style["label"] = "Ton humour calibré"
        if explicit_examples:
            recent = u_style.get("recent_messages", [])
            for ex in explicit_examples:
                ex_c = ex.strip()
                if ex_c and ex_c not in recent:
                    recent.append(ex_c[:220])
            u_style["recent_messages"] = recent[-35:]
            u_style["label"] = "Ton humour calibré"

        recent_msgs = u_style.get("recent_messages", [])
        hints = u_style.get("intent_hints", [])
        notes = u_style.get("humor_notes", "")

        if not recent_msgs and not hints and not notes and not extra_image_bytes:
            save_json(STYLES_FILE, styles)
            return ""

        prompt_parts = [
            "Tu es un linguiste spécialisé dans les conversations Discord/SMS réelles.",
            "Analyse les données ci-dessous appartenant à un utilisateur pour dresser sa fiche d'IMITATION PARFAITE (surtout son humour, son second degré et son écriture réelle) :",
        ]
        if notes:
            prompt_parts.append(f"\nComment il décrit lui-même son humour/style :\n« {notes} »")
        if recent_msgs:
            prompt_parts.append("\nSes vrais messages récents :\n" + "\n".join(f"- {m}" for m in recent_msgs[-25:]))
        if hints:
            prompt_parts.append("\nAutres tournures/intentions qu'il a tapées :\n" + "\n".join(f"- {h}" for h in hints[-10:]))
        if extra_image_bytes:
            prompt_parts.append("\n(Une capture d'écran de ses messages est jointe : lis uniquement SES bulles/messages pour capter son humour, son argot, ses abréviations et sa ponctuation.)")

        prompt_parts.append(
            "\nRédige une fiche de consignes ULTRA PRÉCISE en 5 points courts (max 900 caractères au total) :\n"
            "1. Type d'humour exact (ex: pince-sans-rire, taquin, absurde, autodérision, sarcasme sec... avec le genre de vannes qu'il fait)\n"
            "2. Vocabulaire / tics / abréviations qu'il utilise vraiment (sans en inventer d'autres)\n"
            "3. Casse & ponctuation exacte (minuscules ? pas de points ? virgules ?)\n"
            "4. Longueur typique des messages\n"
            "5. Rappel emojis/fioritures (par défaut : ZERO emoji)"
        )

        dna = await ask_gemini(
            "\n".join(prompt_parts),
            image_bytes=extra_image_bytes,
            mime_type=extra_mime
        )
        u_style["humor_dna"] = dna.strip()[:1000]
        u_style["dna_sample_count"] = len(recent_msgs) + len(hints)
        u_style["updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        styles[uid] = u_style
        save_json(STYLES_FILE, styles)
        return u_style["humor_dna"]
    except Exception:
        return ""
    finally:
        _humor_tasks_inflight.discard(uid)

def maybe_schedule_humor_dna(uid: str):
    if uid in _humor_tasks_inflight:
        return
    try:
        styles = load_json(STYLES_FILE)
        u_style = styles.get(uid)
        if not u_style:
            return
        total = len(u_style.get("recent_messages", [])) + len(u_style.get("intent_hints", []))
        last_cnt = u_style.get("dna_sample_count", 0)
        if total >= 4 and (not u_style.get("humor_dna") or total - last_cnt >= 4):
            asyncio.create_task(analyze_and_save_humor_dna(uid))
    except Exception:
        pass

def get_user_style_description(uid: str) -> str:
    env_preset = os.getenv("PERSONAL_HUMOR_PROFILE", "").strip()
    styles = load_json(STYLES_FILE)
    parts = []
    if env_preset:
        parts.append(f"Profil permanent configuré :\n{env_preset}")
    if uid in styles:
        u_data = styles[uid]
        rules = u_data.get("rules", DEFAULT_STYLE)
        if rules == OLD_DEFAULT_STYLE:
            rules = DEFAULT_STYLE
        notes = u_data.get("humor_notes", "")
        dna = u_data.get("humor_dna", "")
        recent = u_data.get("recent_messages", [])
        hints = u_data.get("intent_hints", [])
        if notes:
            parts.append(f"Humour & consignes de l'utilisateur :\n{notes}")
        if dna:
            parts.append(f"ADN Humour & Écriture analysé :\n{dna}")
        else:
            parts.append(f"Base stylistique :\n{rules}")
        if recent:
            samples_str = "\n".join(f"- {m}" for m in recent[-15:])
            parts.append(f"Vrais messages récents à imiter (ton, humour, taille, orthographe) :\n{samples_str}")
        elif hints:
            hints_str = "\n".join(f"- {h}" for h in hints[-8:])
            parts.append(f"Tournures récentes de l'utilisateur :\n{hints_str}")
    if not parts:
        return DEFAULT_STYLE
    return "\n\n".join(parts)

def get_user_style_label(uid: str) -> str:
    styles = load_json(STYLES_FILE)
    if uid in styles:
        if styles[uid].get("humor_dna") or styles[uid].get("humor_notes"):
            return "Ton humour"
        return styles[uid].get("label", "Naturel")
    return "Naturel"

def set_user_style(uid: str, label: str, rules: str, samples: str = "", recent_messages: list = None):
    styles = load_json(STYLES_FILE)
    existing = styles.get(uid, {})
    existing["label"] = label
    existing["rules"] = rules
    existing["samples"] = samples
    if recent_messages is not None:
        existing["recent_messages"] = recent_messages
    existing["updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    styles[uid] = existing
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
        "title": "🦇 Batman — Page 1/4 : Assistant Personnel & Quotidien",
        "color": discord.Color.dark_theme(),
        "fields": [
            ("💬 MP Directs avec Batman", "Écris-lui ou envoie-lui un **vocal, PDF ou photo** en MP sans commande : il répond avec mémoire + Google !", False),
            ("🏓 /ping", "Latence en ms, état du bot et uptime en direct.", False),
            ("💤 /afk", "`[raison]` — Active ton mode absence ; Batman prévient ceux qui te mentionnent.", False),
            ("⏰ /rappel", "`duree` + `message` — Rappel automatique livré en MP (ex: 10m, 2h, 1j).", False),
            ("📋 /todo & 📝 /note", "Gestionnaire de tâches et carnet de notes personnel interactif.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 2/4 : Super-Pouvoirs Clic-Droit (100% Furtifs)",
        "color": discord.Color.teal(),
        "fields": [
            ("💬 Répondre à ma place", "Lit la discussion (texte, **vocal** ou **image**), écrit sans emojis ni ton IA en imitant **ton humour** : `🎯 + Humour`, `🎭 Mon humour`, `✍️ Guider`, `🔥 Piquant` & copie 1-clic.", False),
            ("🧠 Résumer avec Batman", "**Écoute les messages vocaux en cachette**, lit les PDF/fichiers, résume les longs pavés ou rattrape la discussion manquée !", False),
            ("🎭 Analyser ton & sous-entendus", "Décode l'ironie, les excuses/mythos, l'intérêt caché (même à la voix !) + bouton pour générer 3 réponses.", False),
            ("🔍 Analyser l'image (IA)", "Analyse furtive : résout un **devoir/exo en photo**, lit le texte (OCR) ou explique un mème.", False),
            ("📝 Sauvegarder / 🦇 Avatar HD", "Enregistre un message en note ou récupère l'avatar HD et l'âge du compte d'un profil.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 3/4 : IA Multimodale, Fact-Check & Images HD",
        "color": discord.Color.blue(),
        "fields": [
            ("🧠 /ia", "`question` + `[fichier]` + `[prive]` — Gemini + **Recherche Google en direct** + lecture Image, Vocal, PDF & Code (furtif par défaut !).", False),
            ("🕵️ /verifier", "`affirmation` — **Détecteur de mytho & Fact-Check Google en direct** avec preuves et réponse prête à copier !", False),
            ("🎨 /image & ✨ /imagine", "Génère des images IA Haute Définition (ratios 1:1, 16:9, 9:16 + régénération).", False),
            ("✍️ /reformuler", "`texte` + `style` — Réécrit ton brouillon (Discord naturel, Humour, Pro, Clash, Zéro faute...) sans emojis.", False),
            ("⚡ /repartie", "`sujet` + `[intensite]` — Génère 3 réparties naturelles qui collent à ton humour, sans emojis.", False),
            ("🌍 /traduire", "`texte` + `langue` — Traduction instantanée ultra-naturelle.", False),
        ]
    },
    {
        "title": "🦇 Batman — Page 4/4 : Outils Pratiques & Mini-Jeux",
        "color": discord.Color.purple(),
        "fields": [
            ("📊 /sondage", "`question` + `options` — Crée un sondage interactif avec barres en direct.", False),
            ("🎮 /morpion", "Joue au Morpion (Tic-Tac-Toe) directement dans la discussion avec un ami !", False),
            ("⏱️ /chrono", "`duree` + `nom` — Minuteur Pomodoro qui t'alerte dès la fin.", False),
            ("🌤️ /meteo & 📈 /calcul", "Météo en direct sans clé d'API et calculatrice scientifique.", False),
            ("🎲 /dice & 🦇 /batman", "Lancer de dés et citations cultes du Chevalier Noir.", False),
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
        embed.set_footer(text=f"Page {self.page + 1}/{len(HELP_PAGES)} • Assistant Personnel Batman H24")
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

@bot.tree.command(name="aide", description="Affiche toutes tes fonctionnalités personnelles Batman")
@everywhere
async def aide(interaction: discord.Interaction):
    view = HelpView()
    await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  VUES PARTAGÉES & STUDIO GHOSTWRITER INTERACTIF (100% PERSONNEL)
# ══════════════════════════════════════════════════════════════

class ShareEmbedView(discord.ui.View):
    """Permet d'afficher publiquement dans la discussion un résultat initialement furtif."""
    def __init__(self, author_id: int, embed_to_share: discord.Embed):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.embed_to_share = embed_to_share

    @discord.ui.button(label="Afficher dans la discussion", style=discord.ButtonStyle.secondary, emoji="📢")
    async def share_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        button.disabled = True
        try:
            await interaction.response.send_message(embed=self.embed_to_share, ephemeral=False)
        except Exception:
            try:
                await interaction.channel.send(embed=self.embed_to_share)
                await interaction.response.send_message("✅ Affiché dans la discussion !", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ Impossible de publier ici : `{e}`", ephemeral=True)


async def generate_ghostwriter_card(
    user: discord.abc.User,
    channel,
    message: discord.Message,
    custom_instruction: str = ""
) -> tuple[discord.Embed, str, str, str]:
    """Analyse le message cible (texte, vocal ou image) + la discussion et génère l'embed et les 3 réponses."""
    uid = str(user.id)

    content = message.clean_content or message.content or ""
    media_bytes = None
    media_mime = "image/png"
    media_label = None

    if message.attachments:
        try:
            b_data, b_mime, f_txt, k_lbl = await extract_attachment_payload(message.attachments[0])
            if b_data:
                media_bytes, media_mime, media_label = b_data, b_mime, k_lbl
            elif f_txt:
                content = f"{content}\n[Contenu fichier : {f_txt[:2000]}]" if content else f"[Fichier envoyé : {f_txt[:2000]}]"
                media_label = k_lbl
        except Exception:
            pass

    if not content and not media_bytes:
        raise ValueError("Ce message ne contient ni texte, ni vocal, ni image exploitable.")

    # Récupération automatique du fil de discussion (scan jusqu'à 45 msgs pour capturer les vrais tics & blagues du user)
    convo_lines = []
    user_samples_in_convo = []
    if hasattr(channel, "history"):
        try:
            raw_msgs = []
            async for m in channel.history(limit=45, before=message.created_at):
                txt = m.clean_content or m.content
                if txt and not txt.startswith(("/", "!", ".")):
                    raw_msgs.append((m.author.id, m.author.display_name, txt))
            raw_msgs.reverse()
            for a_id, a_name, txt in raw_msgs[-12:]:
                convo_lines.append(f"{a_name}: {txt}")
            for a_id, _, txt in raw_msgs:
                if a_id == user.id and 3 <= len(txt) <= 220:
                    user_samples_in_convo.append(txt)
                    record_user_writing(uid, txt, is_chat=True)
        except Exception:
            pass

    if user_samples_in_convo:
        maybe_schedule_humor_dna(uid)

    user_style = get_user_style_description(uid)
    style_label = get_user_style_label(uid)

    target_desc = content if content else f"[{media_label} envoyé par {message.author.display_name}]"
    convo_lines.append(f"{message.author.display_name}: {target_desc}")
    convo_context = "\n".join(convo_lines)

    prompt = f"""Tu es le double numérique exact de {user.display_name} sur Discord. Tu dois rédiger 3 vraies réponses comme si {user.display_name} les avait tapées lui-même sur son clavier/téléphone.

--- HISTORIQUE RÉCENT DU CHAT ---
{convo_context}
--- FIN ---

Dernier message de {message.author.display_name} auquel il faut répondre :
« {target_desc} »
"""
    if media_bytes and media_label:
        prompt += f"\n(Média joint : {media_label} — écoute/regarde son contenu pour réagir précisément dessus.)\n"

    prompt += f"""
=== PROFIL, HUMOUR & STYLE DE {user.display_name.upper()} ===
{user_style}
"""
    if user_samples_in_convo:
        prompt += f"\nSes derniers messages directs dans ce salon (copie exactement cette énergie, cette orthographe et cet humour) :\n" + "\n".join(f"- {s}" for s in user_samples_in_convo[-6:]) + "\n"

    if custom_instruction:
        prompt += f"\nCONSIGNE PRIORITAIRE : {custom_instruction}\n"

    prompt += """
INTERDICTIONS ABSOLUES (SI TU VIOLES UNE SEULE DE CES RÈGLES, ÇA SONNE IA) :
1. ZÉRO ÉMOJI / SMILEY : AUCUN emoji Unicode (interdiction totale de 😂 🤣 😅 🔥 👍 💀 😎 ❤️ 🙏 etc.), AUCUN smiley (:), :D, ^^, <3). Du texte pur à 100%.
2. ZÉRO TON IA / SCOLAIRE :
   - Interdiction d'écrire proprement comme un bot ou un mail ("Je suis sur mon PC, tranquille. Et toi, tu fais quoi ?", "Carrément !", "Pas de souci !", "Avec plaisir !", "Super !", "Bien vu !", "Haha c'est énorme !", "Franchement j'avoue !").
   - Écris comme un vrai gars sur Discord : généralement en minuscules (sauf si le profil met des majuscules), SANS point final, sans virgule académique, sans espace devant ? ou !, sans guillemets, sans tiret cadratin (—).
   - Pas de question de politesse forcée à la fin genre "et toi tu fais quoi ?" si ce n'est pas naturel dans le contexte.
3. LONGUEUR ADAPTÉE : Si l'autre envoie 4 mots, réponds en 3 à 9 mots max. Ne fais jamais de pavé.
4. HUMOUR RÉEL (PAS D'HUMOUR DE ROBOT) :
   - Imite l'humour exact du profil ci-dessus (ou s'il n'y en a pas encore, fais du second degré sec / pince-sans-rire / taquin léger entre potes, jamais des blagues lourdes style "en train de sauver le monde hahaha").
   - Contraste concret à respecter :
     * INTERDIT (IA) : "Je suis sur mon PC, tranquille ! Et toi ? 😄"
     * ATTENDU (HUMAIN) : "sur le pc la trkl" / "je fixe mon ecran en attendant un miracle" / "rien de fou sur le pc"
5. LANGUE : Réponds dans la langue du message reçu. S'il est dans une langue étrangère, résume/traduis brièvement en français dans ===INFO=== et garde les 3 options dans la langue de la conv (sans emojis).

Génère exactement 3 options distinctes :
1. ===OPT1=== Naturel (exactement comment l'utilisateur répondrait normalement, crédible à 100%, zéro emoji)
2. ===OPT2=== Avec son humour (vanne pince-sans-rire / second degré / taquin fidèle à son humour, zéro emoji, pas forcé)
3. ===OPT3=== Express (réponse rapide 1 à 6 mots style téléphone, zéro emoji)

FORMAT STRICT (rien d'autre autour) :
===INFO===
(vide si français classique, sinon résumé 1 ligne du vocal/image ou traduction FR)
===OPT1===
(texte pur option 1)
===OPT2===
(texte pur option 2)
===OPT3===
(texte pur option 3)"""

    raw = await ask_gemini(prompt, image_bytes=media_bytes, mime_type=media_mime)
    info_line, opt1, opt2, opt3 = "", "", "", ""
    if "===OPT1===" in raw and "===OPT2===" in raw and "===OPT3===" in raw:
        before_opt1, rest1 = raw.split("===OPT1===", 1)
        if "===INFO===" in before_opt1:
            info_line = before_opt1.split("===INFO===", 1)[1].strip()
        opt1_part, rest2 = rest1.split("===OPT2===", 1)
        opt2_part, opt3_part = rest2.split("===OPT3===", 1)
        opt1 = clean_human_discord_reply(opt1_part, allow_emojis=False, strip_trailing_dot=True)
        opt2 = clean_human_discord_reply(opt2_part, allow_emojis=False, strip_trailing_dot=True)
        opt3 = clean_human_discord_reply(opt3_part, allow_emojis=False, strip_trailing_dot=True)
    else:
        opt1 = clean_human_discord_reply(raw[:240], allow_emojis=False, strip_trailing_dot=True)
        opt2 = "a deux doigts de te croire"
        opt3 = "oe trkl"

    desc = ""
    if len(convo_lines) > 1:
        desc += f"📖 *Fil lu ({len(convo_lines)} msgs)"
        if user_samples_in_convo:
            desc += f" • {len(user_samples_in_convo)} message(s) de toi imités"
        desc += "*"
    if media_label:
        desc += f" • {media_label} analysé"
    if desc:
        desc += "\n"

    preview = content[:130] + ("..." if len(content) > 130 else "") if content else f"[{media_label}]"
    desc += f"En réponse à **{message.author.display_name}** : *« {preview} »*\n"
    if info_line and info_line.lower() not in ("vide", "aucun", "none", "()"):
        desc += f"💡 *{info_line}*\n"
    if custom_instruction:
        desc += f"🎛️ *Mode actif : {custom_instruction[:90]}*\n"

    desc += (
        f"\n**1 · Naturel ({style_label}) :**\n```\n{opt1}\n```\n"
        f"**2 · Ton humour / Vanne :**\n```\n{opt2}\n```\n"
        f"**3 · Express :**\n```\n{opt3}\n```"
    )

    embed = discord.Embed(
        title="💬 Répondre à ta place (Furtif • Zéro Emoji)",
        description=desc[:4000],
        color=discord.Color.teal()
    )
    embed.set_footer(text="Copier 1/2/3 = texte pur sans rien autour • Clique sur « Mon humour » pour lui apprendre tes vannes")
    return embed, opt1, opt2, opt3


class GhostwriterIntentModal(discord.ui.Modal, title="✍️ Lui dire quoi répondre"):
    intent_input = discord.ui.TextInput(
        label="Que veux-tu lui dire en gros ?",
        placeholder="Ex: dis non j'ai la flemme, propose 21h, vanne-le un peu...",
        style=discord.TextStyle.short,
        required=True,
        max_length=200
    )

    def __init__(self, target_message: discord.Message, author_id: int):
        super().__init__()
        self.target_message = target_message
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        uid = str(interaction.user.id)
        record_user_writing(uid, self.intent_input.value, is_chat=False)
        try:
            instruction = f"Exprime cette idée précise dans le style de l'utilisateur (sans emoji) : « {self.intent_input.value} »"
            embed, opt1, opt2, opt3 = await generate_ghostwriter_card(
                interaction.user, interaction.channel, self.target_message, custom_instruction=instruction
            )
            view = GhostwriterView(self.target_message, self.author_id, opt1, opt2, opt3)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


class CalibrateHumorModal(discord.ui.Modal, title="🎭 Apprendre ton humour à Batman"):
    humor_desc = discord.ui.TextInput(
        label="Décris ton humour & ton écriture (optionnel)",
        placeholder="Ex: second degré sec, pince-sans-rire, taquin, tout en minuscules, jamais d'emojis, messages courts",
        style=discord.TextStyle.short,
        required=False,
        max_length=300
    )
    humor_examples = discord.ui.TextInput(
        label="Colle 2 à 6 vrais messages/vannes de toi",
        placeholder="Ex:\nje rentabilise ma chaise\nt'es vachement convaincu frr\na deux doigts d'avoir raison\nbof flemme un peu la",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1200
    )

    def __init__(self, target_message: discord.Message, author_id: int):
        super().__init__()
        self.target_message = target_message
        self.author_id = author_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        uid = str(interaction.user.id)
        notes = (self.humor_desc.value or "").strip()
        raw_ex = (self.humor_examples.value or "").strip()
        examples = [line.strip() for line in raw_ex.splitlines() if line.strip()]
        if not notes and not examples:
            return await interaction.followup.send("❌ Remplis au moins la description ou quelques exemples de tes messages.", ephemeral=True)
        try:
            dna = await analyze_and_save_humor_dna(
                uid=uid,
                explicit_notes=notes or None,
                explicit_examples=examples or None
            )
            embed, opt1, opt2, opt3 = await generate_ghostwriter_card(
                interaction.user,
                interaction.channel,
                self.target_message,
                custom_instruction="Applique dès maintenant le nouvel humour et les expressions calibrées, zéro emoji."
            )
            if dna:
                embed.add_field(name="🧠 Humour mémorisé par Batman", value=dna[:350], inline=False)
            view = GhostwriterView(self.target_message, self.author_id, opt1, opt2, opt3)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur : `{e}`", ephemeral=True)


class GhostwriterView(discord.ui.View):
    def __init__(self, target_message: discord.Message, author_id: int, opt1: str, opt2: str, opt3: str):
        super().__init__(timeout=900)
        self.target_message = target_message
        self.author_id = author_id
        self.opt1 = opt1
        self.opt2 = opt2
        self.opt3 = opt3

    async def _copy_raw(self, interaction: discord.Interaction, text: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        # Envoie UNIQUEMENT le texte brut en éphémère : 0 emoji, 0 caractère parasite
        await interaction.response.send_message(text, ephemeral=True)

    async def _rewrite_in_place(self, interaction: discord.Interaction, instruction: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.defer()
        try:
            embed, o1, o2, o3 = await generate_ghostwriter_card(
                interaction.user, interaction.channel, self.target_message, custom_instruction=instruction
            )
            self.opt1, self.opt2, self.opt3 = o1, o2, o3
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)

    # Rangée 0 : Copie pure 1-clic (texte brut pour coller depuis TON vrai compte)
    @discord.ui.button(label="Copier 1", style=discord.ButtonStyle.success, emoji="📋", row=0)
    async def btn_copy1(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy_raw(interaction, self.opt1)

    @discord.ui.button(label="Copier 2", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def btn_copy2(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy_raw(interaction, self.opt2)

    @discord.ui.button(label="Copier 3", style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def btn_copy3(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy_raw(interaction, self.opt3)

    # Rangée 1 : Ajustement rapide 100% sans emojis ni ton IA
    @discord.ui.button(label="Guider", style=discord.ButtonStyle.primary, emoji="✍️", row=1)
    async def btn_guide(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.send_modal(GhostwriterIntentModal(self.target_message, self.author_id))

    @discord.ui.button(label="+ Humour", style=discord.ButtonStyle.secondary, emoji="🎯", row=1)
    async def btn_humor(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._rewrite_in_place(
            interaction,
            "Pousse encore plus l'humour personnel (vannes pince-sans-rire, second degré absurde ou taunt amical naturel) tout en restant 100% crédible et avec ZERO emoji."
        )

    @discord.ui.button(label="Piquant", style=discord.ButtonStyle.secondary, emoji="🔥", row=1)
    async def btn_spicy(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._rewrite_in_place(
            interaction,
            "Ton plus sec, taquin et incisif avec bonne répartie Discord, sans vulgarité lourde, sans phrases de robot et ZERO emoji."
        )

    @discord.ui.button(label="+ Court", style=discord.ButtonStyle.secondary, emoji="📏", row=1)
    async def btn_short(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._rewrite_in_place(
            interaction,
            "Réponses ultra courtes (2 à 6 mots max), en minuscules, zéro ponctuation scolaire, ZERO emoji."
        )

    @discord.ui.button(label="Autres", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def btn_regen(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._rewrite_in_place(
            interaction,
            "Propose 3 nouvelles réponses totalement différentes des précédentes, toujours 100% humaines et ZERO emoji."
        )

    # Rangée 2 : Calibration humour + envoi via bot optionnel
    @discord.ui.button(label="Mon humour", style=discord.ButtonStyle.secondary, emoji="🎭", row=2)
    async def btn_calibrate(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.send_modal(CalibrateHumorModal(self.target_message, self.author_id))

    @discord.ui.button(label="Poster (Bot)", style=discord.ButtonStyle.secondary, emoji="🤖", row=2)
    async def btn_post_bot(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        content = f"> *En réponse à {self.target_message.author.display_name} :*\n{self.opt1}"
        # 1. Webhook si le bot est sur un serveur avec permission Webhook
        if interaction.guild and hasattr(interaction.channel, "webhooks"):
            try:
                webhooks = await interaction.channel.webhooks()
                wh = next((w for w in webhooks if w.name == "BatmanGhostwriter" and w.token), None)
                if not wh:
                    wh = await interaction.channel.create_webhook(name="BatmanGhostwriter")
                await wh.send(content=content, username=interaction.user.display_name, avatar_url=interaction.user.display_avatar.url)
                return await interaction.response.send_message("✅ Posté avec ton pseudo et ton avatar !", ephemeral=True)
            except Exception:
                pass
        # 2. Réponse publique User App (affiche Batman [APP])
        try:
            await interaction.response.send_message(content=content, ephemeral=False)
        except Exception:
            try:
                await interaction.channel.send(content=content)
                await interaction.response.send_message("✅ Posté dans le salon !", ephemeral=True)
            except Exception:
                await interaction.response.send_message(self.opt1, ephemeral=True)


class BridgeToGhostwriterView(discord.ui.View):
    """Bouton passerelle permettant de générer 3 réponses directement après un résumé vocal ou une analyse de ton."""
    def __init__(self, target_message: discord.Message, author_id: int, context_hint: str = ""):
        super().__init__(timeout=600)
        self.target_message = target_message
        self.author_id = author_id
        self.context_hint = context_hint

    @discord.ui.button(label="Préparer 3 réponses adaptées", style=discord.ButtonStyle.success, emoji="💬")
    async def make_replies(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            hint = f"Tiens compte de ce contexte : {self.context_hint[:250]}" if self.context_hint else ""
            embed, o1, o2, o3 = await generate_ghostwriter_card(
                interaction.user, interaction.channel, self.target_message, custom_instruction=hint
            )
            view = GhostwriterView(self.target_message, self.author_id, o1, o2, o3)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  MENUS CONTEXTUELS CLIC-DROIT (Discord Apps — 100% Personnels)
# ══════════════════════════════════════════════════════════════

# 1. Clic droit sur un message -> Résumer avec Batman (Texte, Message Vocal, PDF, Fichier ou Discussion !)
@bot.tree.context_menu(name="🧠 Résumer avec Batman")
@everywhere
async def context_summarize(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True, thinking=True)
    content = message.clean_content or message.content or ""
    media_bytes, media_mime, file_text, kind_label = None, "image/png", None, None

    if message.attachments:
        try:
            media_bytes, media_mime, file_text, kind_label = await extract_attachment_payload(message.attachments[0])
        except Exception:
            pass

    try:
        # Cas A : Message Vocal / Audio Discord !
        if media_bytes and kind_label and "Audio" in kind_label:
            prompt = (
                f"Écoute attentivement ce message vocal envoyé par {message.author.display_name}.\n"
                "Donne en français :\n"
                "1. 🗣️ **Transcription fidèle** (ce que la personne dit exactement)\n"
                "2. ⚡ **L'essentiel en 2 points** (ce qu'il faut retenir ou la question posée)"
            )
            summary = await ask_gemini(prompt, image_bytes=media_bytes, mime_type=media_mime)
            title = f"🎙️ Vocal de {message.author.display_name} (Écouté en furtif)"

        # Cas B : PDF ou Fichier texte/code
        elif (media_bytes and kind_label and "PDF" in kind_label) or file_text:
            body = f"\n\nContenu :\n{file_text}" if file_text else ""
            prompt = f"Résume clairement ce document ({kind_label}) en points clés faciles à lire, et signale les infos importantes :{body}"
            summary = await ask_gemini(prompt, image_bytes=media_bytes, mime_type=media_mime or "application/pdf")
            title = f"📄 Résumé du fichier ({message.author.display_name})"

        # Cas C : Texte court -> Rattrapage des derniers messages de la discussion si l'historique est accessible !
        elif content and len(content) < 160 and hasattr(interaction.channel, "history"):
            convo = []
            try:
                async for m in interaction.channel.history(limit=25):
                    t = m.clean_content or m.content
                    if t and not t.startswith(("/", "!", ".")):
                        convo.append(f"{m.author.display_name}: {t}")
                convo.reverse()
            except Exception:
                pass

            if len(convo) >= 4:
                joined = "\n".join(convo)
                prompt = (
                    f"Voici les {len(convo)} derniers messages d'une discussion Discord :\n{joined}\n\n"
                    "Fais un récapitulatif ultra-clair (« Ce que tu as raté ») en 3-4 puces : de quoi ils parlent, qui pense quoi, et quelle est la dernière question/info."
                )
                summary = await ask_gemini(prompt)
                title = f"📖 Récap de la discussion ({len(convo)} derniers messages)"
            else:
                prompt = f"Explique et résume clairement ce message (et traduis-le s'il n'est pas en français) :\n\n{content}"
                summary = await ask_gemini(prompt)
                title = "🧠 Résumé & Explication par Batman"

        # Cas D : Long pavé de texte
        elif content:
            prompt = (
                "Fais un résumé ultra-clair et percutant en 2 à 4 points clés de ce message "
                "(s'il est en langue étrangère, résume-le directement en français) :\n\n" + content
            )
            summary = await ask_gemini(prompt)
            title = f"🧠 Résumé du pavé de {message.author.display_name}"
        else:
            return await interaction.followup.send("❌ Ce message ne contient ni texte, ni message vocal, ni document à résumer.", ephemeral=True)

        embed = discord.Embed(title=title, description=summary[:3800], color=discord.Color.teal())
        embed.set_footer(text="100% Furtif (visible uniquement par toi)")
        view = BridgeToGhostwriterView(message, interaction.user.id, context_hint=summary[:250])
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# 2. Clic droit sur un message -> Sauvegarder en note
@bot.tree.context_menu(name="📝 Sauvegarder en note")
@everywhere
async def context_save_note(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content
    if not content and message.attachments:
        content = "\n".join(a.url for a in message.attachments)
    if not content:
        return await interaction.response.send_message("❌ Ce message ne contient aucun contenu à sauvegarder.", ephemeral=True)

    uid = str(interaction.user.id)
    notes = load_json(NOTES_FILE)
    lst = notes.get(uid, [])

    title = f"Message de {message.author.display_name} ({datetime.now().strftime('%d/%m')})"
    lst.append({
        "title": title,
        "content": content[:1000],
        "date": datetime.now().strftime("%d/%m %H:%M")
    })
    notes[uid] = lst
    save_json(NOTES_FILE, notes)

    embed = discord.Embed(
        title="📝 Message sauvegardé dans tes notes !",
        description=f"**{title}**\n> {content[:200]}",
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
        description=f"**Pseudo affiché :** `{user.display_name}`\n**Nom d'utilisateur :** `{user.name}`\n**ID :** `{user.id}`",
        color=discord.Color.dark_theme()
    )
    embed.add_field(name="📅 Compte créé le", value=f"<t:{created_ts}:D> (<t:{created_ts}:R>)")
    embed.add_field(name="🤖 Bot ?", value="Oui" if user.bot else "Non")
    embed.set_image(url=avatar_url)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Télécharger Avatar HD", url=avatar_url, emoji="🖼️"))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# 4. Clic droit sur un message -> Analyser l'image avec l'IA (100% Furtif + OCR + Résolution d'exos)
@bot.tree.context_menu(name="🔍 Analyser l'image (IA)")
@everywhere
async def context_analyze_image(interaction: discord.Interaction, message: discord.Message):
    image_url = None
    mime_type = "image/png"
    img_bytes = None

    for att in message.attachments:
        ct = att.content_type or ""
        if ct.startswith("image/") or any(att.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
            img_bytes = await att.read()
            mime_type = ct if ct.startswith("image/") else ("image/jpeg" if att.filename.lower().endswith((".jpg", ".jpeg")) else "image/png")
            image_url = att.url
            break

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
        return await interaction.response.send_message("❌ Aucune image trouvée dans ce message.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    prompt = (
        "Analyse cette image en français avec perspicacité :\n"
        "- S'il s'agit d'un **exercice, devoir, QCM ou code/erreur**, donne directement la **solution claire et expliquée** !\n"
        "- S'il s'agit d'une **capture d'écran ou texte en langue étrangère**, traduis et explique l'essentiel.\n"
        "- S'il s'agit d'un **mème, photo, objet ou lieu**, identifie-le précisément et explique le contexte ou la référence."
    )
    try:
        analysis = await ask_gemini(prompt, image_bytes=img_bytes, mime_type=mime_type)
        embed = discord.Embed(
            title="🔍 Analyse d'image IA (Furtive)",
            description=analysis[:3800],
            color=discord.Color.teal()
        )
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.set_footer(text=f"Visible uniquement par toi • Image de {message.author.display_name}")
        view = ShareEmbedView(interaction.user.id, embed)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# 5. Clic droit sur un message -> Répondre à ma place (Ghostwriter V2)
@bot.tree.context_menu(name="💬 Répondre à ma place")
@everywhere
async def context_reply_for_me(interaction: discord.Interaction, message: discord.Message):
    if not (message.clean_content or message.content) and not message.attachments:
        return await interaction.response.send_message("❌ Ce message est vide.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        embed, opt1, opt2, opt3 = await generate_ghostwriter_card(interaction.user, interaction.channel, message)
        view = GhostwriterView(message, interaction.user.id, opt1, opt2, opt3)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=True)


# 6. Clic droit sur un message -> Analyser le ton & les sous-entendus (Texte & Vocaux !)
@bot.tree.context_menu(name="🎭 Analyser ton & sous-entendus")
@everywhere
async def context_analyze_tone(interaction: discord.Interaction, message: discord.Message):
    content = message.clean_content or message.content or ""
    media_bytes, media_mime, _, kind_label = None, "audio/ogg", None, None
    if message.attachments:
        try:
            b_data, b_mime, _, k_lbl = await extract_attachment_payload(message.attachments[0])
            if b_data and k_lbl and ("Audio" in k_lbl or "Image" in k_lbl):
                media_bytes, media_mime, kind_label = b_data, b_mime, k_lbl
        except Exception:
            pass

    if not content and not media_bytes:
        return await interaction.response.send_message("❌ Ce message ne contient ni texte ni vocal à analyser.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)

    convo_lines = []
    if hasattr(interaction.channel, "history"):
        try:
            async for m in interaction.channel.history(limit=6, before=message.created_at):
                txt = m.clean_content or m.content
                if txt and not txt.startswith(("/", "!", ".")):
                    convo_lines.append(f"{m.author.display_name}: {txt}")
            convo_lines.reverse()
        except Exception:
            pass
    target_disp = content if content else f"[{kind_label}]"
    convo_lines.append(f"{message.author.display_name}: {target_disp}")
    convo_context = "\n".join(convo_lines)

    prompt = f"""Fais une analyse psychologique et sociale ultra-fine de ce message Discord envoyé par {message.author.display_name} :
« {target_disp} »
"""
    if media_bytes:
        prompt += f"(Analyse aussi l'intonation de la voix ou l'image jointe : {kind_label})\n"

    prompt += f"""
Contexte récent de la discussion :
{convo_context}

Donne de manière directe et perspicace :
1. 🎭 **Vrai ton & Émotion** (ex: Taquin, Froid/distant, Intéressé/Flirt, Passif-agressif, Sincère, Gêné...)
2. 🕵️ **Sous-entendus & Indice de sincérité** (ce que la personne pense vraiment derrière ses mots, ou si ça sent l'excuse/mytho)
3. 💡 **Meilleur move** (comment réagir pour garder l'avantage ou gérer la situation intelligemment)

Reste concis et percutant."""

    try:
        analysis = await ask_gemini(prompt, image_bytes=media_bytes, mime_type=media_mime)
        header_quote = f"> *« {content[:180]} »*\n\n" if content else f"> *{kind_label} analysé*\n\n"
        embed = discord.Embed(
            title=f"🎭 Décodeur Psychologique : {message.author.display_name}",
            description=f"{header_quote}{analysis[:3500]}",
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"100% Furtif • Contexte de {len(convo_lines)} message(s)")
        view = BridgeToGhostwriterView(message, interaction.user.id, context_hint=analysis[:300])
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
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
#  ASSISTANT IA GEMINI (MÉMOIRE, RECHERCHE GOOGLE, VOCAUX, PDF, IMAGES)
# ══════════════════════════════════════════════════════════════
class RawCopyView(discord.ui.View):
    """Bouton 1-clic pour isoler le texte brut à copier facilement sur PC ou mobile."""
    def __init__(self, author_id: int, raw_text: str):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.raw_text = raw_text[:1990]

    @discord.ui.button(label="Copier le texte pur", style=discord.ButtonStyle.success, emoji="📋")
    async def copy_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.send_message(self.raw_text, ephemeral=True)


@bot.tree.command(name="ia", description="Pose n'importe quelle question à Batman (Google en direct, photo, devoir, vocal, PDF)")
@everywhere
@app_commands.describe(
    question="Ta question, devoir, recherche d'actu ou consigne",
    fichier="Image, message vocal/audio, PDF ou fichier texte/code à analyser (optionnel)",
    prive="Mode furtif : visible uniquement par toi (Activé par défaut !)"
)
async def ia_command(
    interaction: discord.Interaction,
    question: str,
    fichier: discord.Attachment = None,
    prive: bool = True
):
    await interaction.response.defer(ephemeral=prive, thinking=True)
    try:
        uid = str(interaction.user.id)
        media_bytes, mime_type, file_text, kind_label = None, "image/png", None, None

        if fichier is not None:
            media_bytes, mime_type, file_text, kind_label = await extract_attachment_payload(fichier)
            if not media_bytes and not file_text:
                return await interaction.followup.send(
                    "❌ Format non pris en charge. Envoie une **image**, un **audio/vocal**, un **PDF** ou un **fichier texte/code** !",
                    ephemeral=prive
                )

        full_prompt = question
        if file_text:
            full_prompt = f"{question}\n\n--- CONTENU DU FICHIER ({fichier.filename}) ---\n{file_text}"

        history = get_user_memory(uid)
        system_prompt = (
            f"Tu es Batman, l'assistant personnel ultra-intelligent de {interaction.user.display_name}. "
            "Tu es direct, perspicace, précis et fiable. Si on te demande une info récente, utilise la recherche Google. "
            "Si on t'envoie un exercice ou du code, résous-le clairement étape par étape en français."
        )

        answer = await ask_gemini(
            prompt=full_prompt,
            image_bytes=media_bytes,
            mime_type=mime_type or "image/png",
            history=history,
            system_instruction=system_prompt,
            use_search=(media_bytes is None)
        )

        append_user_memory(uid, question, answer)

        embed = discord.Embed(title="🧠 Batman IA", description=answer[:3900], color=discord.Color.teal())
        if fichier is not None and kind_label and "Image" in kind_label:
            embed.set_thumbnail(url=fichier.url)

        turns = len(get_user_memory(uid)) // 2
        footer = f"Mémoire: {turns} échange(s)"
        if kind_label:
            footer += f" • {kind_label}"
        else:
            footer += " • 🌐 Web Google actif"
        if prive:
            footer += " • 🥷 Furtif"
        embed.set_footer(text=footer)

        view = ShareEmbedView(interaction.user.id, embed) if prive else None
        if view:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur IA : `{e}`", ephemeral=prive)


@bot.tree.command(name="verifier", description="🕵️ Détecteur de mytho & Fact-Check Google en direct (100% furtif)")
@everywhere
@app_commands.describe(
    affirmation="L'info, la rumeur ou ce que quelqu'un vient d'affirmer dans la discussion"
)
async def verifier_command(interaction: discord.Interaction, affirmation: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    user_style = get_user_style_description(uid)
    prompt = f"""Vérifie rigoureusement cette affirmation à l'aide des informations récentes sur le web :
« {affirmation} »

Réponds en français exactement selon cette structure :
VERDICT : (écris ✅ VRAI, ❌ FAUX / MYTHO, ou ⚠️ NUANCÉ / INCOMPLET)
PREUVE : (2 à 3 phrases claires avec les vrais chiffres, dates ou faits vérifiés)
===REPLIQUE===
(une phrase 100% naturelle et courte pour répondre sur Discord sans sonner comme une IA et SANS AUCUN EMOJI, en imitant ce style/humour si pertinent : {user_style[:400]})"""

    try:
        raw = await ask_gemini(prompt, use_search=True)
        body, replique = raw, ""
        if "===REPLIQUE===" in raw:
            parts = raw.split("===REPLIQUE===", 1)
            body = parts[0].strip()
            replique = clean_human_discord_reply(parts[1], allow_emojis=False, strip_trailing_dot=True)

        desc = f"**Affirmation testée :** *« {affirmation[:180]} »*\n\n{body}"
        if replique:
            desc += f"\n\n💬 **Phrase prête à envoyer dans le chat :**\n```\n{replique}\n```"

        color = discord.Color.green() if "✅" in body else (discord.Color.red() if "❌" in body else discord.Color.orange())
        embed = discord.Embed(title="🕵️ Bat-Vérificateur & Détecteur de Mytho", description=desc[:3900], color=color)
        embed.set_footer(text="100% Furtif (visible uniquement par toi) • Vérifié via Google Search")
        view = RawCopyView(interaction.user.id, replique) if replique else ShareEmbedView(interaction.user.id, embed)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur lors de la vérification : `{e}`", ephemeral=True)


# ══════════════════════════════════════════════════════════════
#  OUTILS DE CONVERSATION : REFORMULATION & RÉPARTIES (100% FURTIFS)
# ══════════════════════════════════════════════════════════════
REFORMULER_STYLES = [
    app_commands.Choice(name="📱 Message Discord naturel (sans emoji)", value="sms"),
    app_commands.Choice(name="🔤 Zéro faute (garde exactement mon ton)", value="ortho"),
    app_commands.Choice(name="😂 Avec mon humour (second degré / vanne)", value="humour"),
    app_commands.Choice(name="⚡ Clash sec / Répartie (sans insultes)", value="clash"),
    app_commands.Choice(name="💼 Professionnel & Poli", value="pro"),
    app_commands.Choice(name="🤝 Diplomate & Posé", value="diplomate"),
    app_commands.Choice(name="📏 Ultra-court (2-6 mots)", value="court"),
    app_commands.Choice(name="🦇 Style Batman", value="batman")
]

REFORMULER_STYLE_PROMPTS = {
    "sms": "Message Discord 100% humain et naturel : minuscules, pas de point final scolaire, zéro ponctuation rigide, pas de tournure d'IA, ZERO emoji.",
    "ortho": "Corrige uniquement les grosses fautes d'orthographe/conjugaison tout en gardant exactement le même ton, les mêmes abréviations, sans rendre la phrase scolaire ni ajouter d'emoji.",
    "humour": "Ajoute ou adapte la phrase avec l'humour personnel de l'utilisateur (second degré, pince-sans-rire, taquin naturel), crédible sur Discord, ZERO emoji, ZERO blague de robot.",
    "clash": "Répartie sèche, tranchante et naturelle sur Discord sans insultes ni ponctuation robotique, ZERO emoji.",
    "pro": "Professionnel, courtois, clair et irréprochable, sans emojis.",
    "diplomate": "Diplomatique, posé, calme et naturel, sans emojis.",
    "court": "Ultra court (2 à 6 mots max), droit au but, minuscules naturelles, ZERO emoji.",
    "batman": "Sombre, laconique, calme et charismatique façon Batman, ZERO emoji."
}


class ThreeOptionsCopyView(discord.ui.View):
    """Permet de copier l'une des 3 réparties pures en 1 clic sans aucun caractère parasite."""
    def __init__(self, author_id: int, r1: str, r2: str, r3: str):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.r1 = r1
        self.r2 = r2
        self.r3 = r3

    async def _copy(self, interaction: discord.Interaction, txt: str):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Action non autorisée.", ephemeral=True)
        await interaction.response.send_message(txt, ephemeral=True)

    @discord.ui.button(label="Copier 1", style=discord.ButtonStyle.success, emoji="📋")
    async def c1(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy(interaction, self.r1)

    @discord.ui.button(label="Copier 2", style=discord.ButtonStyle.primary, emoji="📋")
    async def c2(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy(interaction, self.r2)

    @discord.ui.button(label="Copier 3", style=discord.ButtonStyle.secondary, emoji="📋")
    async def c3(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._copy(interaction, self.r3)


@bot.tree.command(name="reformuler", description="Réécrit ton message sans ton IA ni emojis en mode furtif")
@everywhere
@app_commands.describe(
    texte="Ton brouillon ou ce que tu veux dire",
    style="Le style souhaité"
)
@app_commands.choices(style=REFORMULER_STYLES)
async def reformuler(
    interaction: discord.Interaction,
    texte: str,
    style: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    record_user_writing(uid, texte, is_chat=False)
    user_style = get_user_style_description(uid)
    style_desc = REFORMULER_STYLE_PROMPTS.get(style.value, style.value)
    is_pro = style.value in ("pro", "diplomate")

    prompt = (
        f"Réécris le message suivant selon cette consigne : {style_desc}\n"
        f"Profil & humour de l'utilisateur à respecter si compatible :\n{user_style[:600]}\n\n"
        "RÈGLES STRICTES : ZÉRO EMOJI (aucun emoji Unicode ni smiley), zéro guillemets, zéro commentaire autour, "
        "et ne sonne surtout pas comme une IA.\n"
        f"Message de base :\n{texte}"
    )
    try:
        raw = await ask_gemini(prompt)
        result = clean_human_discord_reply(raw, allow_emojis=False, strip_trailing_dot=(not is_pro))
        embed = discord.Embed(
            title=f"✍️ Message prêt ({style.name})",
            description=f"**Ton brouillon :**\n> *« {texte[:300]} »*\n\n**À copier :**\n```\n{result[:1800]}\n```",
            color=discord.Color.blue()
        )
        embed.set_footer(text="100% Furtif • Zéro emoji • Clique sur « Copier le texte pur »")
        await interaction.followup.send(embed=embed, view=RawCopyView(interaction.user.id, result), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur : `{e}`", ephemeral=True)


REPARTIE_PROMPTS = {
    "taquin": "taquin, second degré léger et drôle entre potes",
    "piquant": "pince-sans-rire, sec, malin et piquant",
    "clash": "répartie sèche et dévastatrice sans insultes vulgaires ni ton scolaire",
    "batman": "froid, calme, laconique et charismatique façon Batman"
}

@bot.tree.command(name="repartie", description="Génère 3 réparties naturelles qui collent à ton humour (furtif)")
@everywhere
@app_commands.describe(
    sujet="La pique reçue, le message ou la situation",
    intensite="Niveau d'intensité de la répartie"
)
@app_commands.choices(intensite=[
    app_commands.Choice(name="😄 Taquin & Bon enfant", value="taquin"),
    app_commands.Choice(name="🔥 Piquant & Pince-sans-rire", value="piquant"),
    app_commands.Choice(name="⚡ Clash sec (sans insultes)", value="clash"),
    app_commands.Choice(name="🦇 Punchline Batman", value="batman")
])
async def repartie(
    interaction: discord.Interaction,
    sujet: str,
    intensite: app_commands.Choice[str] = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    user_style = get_user_style_description(uid)
    lvl = REPARTIE_PROMPTS.get(intensite.value, "pince-sans-rire, malin et naturel") if intensite else "pince-sans-rire, malin et naturel"

    prompt = f"""Génère 3 réparties 100% humaines sur Discord pour répondre à : « {sujet} »
Ton demandé : {lvl}.

Profil & humour de l'utilisateur à imiter :
{user_style[:700]}

INTERDICTIONS ABSOLUES :
- ZÉRO EMOJI / SMILEY (aucun 😂, 🔥, 💀, :), ^^ etc.). Texte brut pur uniquement.
- ZÉRO phrase d'IA ou de vieux livre ("Bien envoyé !", "Mon cher", "Haha t'es drôle !", guillemets, tirets cadratins —).
- Écris court et naturel (minuscules ou ponctuation Discord réelle, sans point final scolaire).

RÉPONDS EXACTEMENT AU FORMAT :
===R1===
(répartie 1 pure)
===R2===
(répartie 2 pure)
===R3===
(répartie 3 pure)"""

    try:
        raw = await ask_gemini(prompt)
        if "===R1===" in raw and "===R2===" in raw and "===R3===" in raw:
            p1 = raw.split("===R1===", 1)[1]
            r1_raw, rest = p1.split("===R2===", 1)
            r2_raw, r3_raw = rest.split("===R3===", 1)
            r1 = clean_human_discord_reply(r1_raw, allow_emojis=False, strip_trailing_dot=True)
            r2 = clean_human_discord_reply(r2_raw, allow_emojis=False, strip_trailing_dot=True)
            r3 = clean_human_discord_reply(r3_raw, allow_emojis=False, strip_trailing_dot=True)
            desc = (
                f"**Face à :** *« {sujet[:150]} »*\n\n"
                f"**1 · Naturelle :**\n```\n{r1}\n```\n"
                f"**2 · Sèche / Humour :**\n```\n{r2}\n```\n"
                f"**3 · Courte :**\n```\n{r3}\n```"
            )
            view = ThreeOptionsCopyView(interaction.user.id, r1, r2, r3)
        else:
            cleaned = strip_emojis(raw)
            desc = f"**Face à :** *« {sujet[:150]} »*\n\n{cleaned[:3500]}"
            view = RawCopyView(interaction.user.id, cleaned)

        embed = discord.Embed(
            title="⚡ 3 Réparties Furtives (Zéro Emoji)",
            description=desc[:3900],
            color=discord.Color.dark_red()
        )
        embed.set_footer(text="100% Furtif • Ton humour imité • Clique sur Copier 1/2/3 !")
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Erreur : `{e}`", ephemeral=True)


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
    app_commands.Choice(name="🎨 Standard / Naturel", value="naturel"),
    app_commands.Choice(name="📸 Photoréaliste", value="photo"),
    app_commands.Choice(name="🦇 Batman / Gotham Dark", value="batman"),
    app_commands.Choice(name="🏮 Anime / Manga", value="anime"),
    app_commands.Choice(name="⚡ Cyberpunk", value="cyberpunk"),
    app_commands.Choice(name="🖌️ Peinture à l'huile", value="huile"),
    app_commands.Choice(name="🕹️ Pixel Art", value="pixel")
]

IMAGE_STYLE_PROMPTS = {
    "naturel": "Naturel",
    "photo": "photorealistic, 8k photography, highly detailed, sharp focus",
    "batman": "dark gothic style, Batman comics noir, moody dramatic shadows, cinematic rain",
    "anime": "anime aesthetic, Makoto Shinkai style, vibrant colors, detailed line art",
    "cyberpunk": "cyberpunk city, neon lights, futuristic, rainy night, synthwave",
    "huile": "oil painting on canvas, expressive brush strokes, classical art",
    "pixel": "pixel art 32-bit, retro gaming aesthetic"
}

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
        chosen_style = IMAGE_STYLE_PROMPTS.get(style.value, "Naturel") if style else "Naturel"
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
        try:
            await bot.start(TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            print("⚠️ Message Content Intent non activé dans le Developer Portal.", flush=True)
            print("🔄 Bascule automatique sur les intents standards sans privilège...", flush=True)
            bot._connection._intents = discord.Intents.default()
            await bot.connect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Arrêt.", flush=True)
