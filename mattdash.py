#!/usr/bin/env python3
"""
mattdash — Dashboard terminal perso par Matt
Auteur : Matt
Licence : MIT

Ce que ça fait :
  - Stats système live (CPU, RAM, disque, load, IP)
  - Météo de ta ville (variable dans la config, pas hardcodée)
  - 15 derniers DMs Discord, ceux sans réponse en gras
  - Envoi de messages et fichiers/images Discord
  - Export HTML d'un channel avec formatage markdown Discord complet
  - Sidebar avec les membres si c'est un salon de serveur
  - Ping latence vers n'importe quel hôte ou IP
"""

import curses
import threading
import time
import subprocess
import json
import re
import sys
import socket
import html as html_mod
from datetime import datetime
from pathlib import Path

# Où on stocke la config et les logs
CONFIG_FILE = Path.home() / ".config" / "mattdash" / "config.json"
LOG_DIR     = Path.home() / "Documents" / "mattdash-logs"

# Valeurs par défaut — utilisées si la clé manque dans config.json
# La ville météo est ici en variable, pas hardcodée dans le code
DEFAULT_CONFIG = {
    "discord_token":       "",
    "weather_city":        "",                # vide = désactivé, config city <ville,Pays>
    "dm_refresh_interval": 60,                # secondes entre refresh DMs
    "my_discord_id":       "",                # ton ID pour détecter les msgs sans réponse
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def load_config():
    """Charge la config JSON, complète avec les défauts pour les clés manquantes."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    """Sauvegarde la config proprement dans ~/.config/mattdash/config.json"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# STATS SYSTÈME
# ─────────────────────────────────────────────────────────────────────────────

def get_cpu():
    """Usage CPU en %. psutil si dispo, sinon on lit /proc/stat directement."""
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except Exception:
        try:
            with open("/proc/stat") as f:
                vals = list(map(int, f.readline().split()[1:]))
            idle = vals[3]
            total = sum(vals)
            return round((1 - idle / total) * 100, 1) if total else 0.0
        except Exception:
            return 0.0


def get_ram():
    """RAM : (utilisée Mo, totale Mo, pct). psutil ou /proc/meminfo."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return m.used // (1024 * 1024), m.total // (1024 * 1024), m.percent
    except Exception:
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k.strip()] = int(v.split()[0])
            total = info["MemTotal"] // 1024
            avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
            used  = total - avail
            return used, total, round(used / total * 100, 1) if total else 0
        except Exception:
            return 0, 0, 0.0


def get_disk():
    """Espace disque racine en Go. psutil ou df."""
    try:
        import psutil
        d = psutil.disk_usage("/")
        return d.used // (1024**3), d.total // (1024**3), d.percent
    except Exception:
        try:
            parts = subprocess.check_output(["df", "-BG", "/"], text=True).splitlines()[1].split()
            return int(parts[2].rstrip("G")), int(parts[1].rstrip("G")), float(parts[4].rstrip("%"))
        except Exception:
            return 0, 0, 0.0


def get_uptime():
    """Uptime formaté '3h 42m' depuis /proc/uptime."""
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"
    except Exception:
        return "?"


def get_load():
    """Load average 1/5/15 min."""
    try:
        with open("/proc/loadavg") as f:
            p = f.read().split()
        return p[0], p[1], p[2]
    except Exception:
        return "?", "?", "?"


def get_local_ip():
    """IP locale via socket UDP fake vers 8.8.8.8 (aucun paquet réellement envoyé)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"


# ─────────────────────────────────────────────────────────────────────────────
# MÉTÉO — wttr.in, zéro API key
# ─────────────────────────────────────────────────────────────────────────────

def fetch_weather(city):
    """
    Météo de la ville passée en param (vient de la config, pas hardcodée).
    wttr.in format 3 = une ligne courte : 'Paris: ⛅ +12°C'
    On peut changer la ville avec : config city Paris,France
    """
    if not city:
        return "Météo non configurée — tape : config city Paris,France"
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://wttr.in/{city}?format=3",
            headers={"User-Agent": "curl/7.68"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return "Météo indisponible"


# ─────────────────────────────────────────────────────────────────────────────
# PING
# ─────────────────────────────────────────────────────────────────────────────

def ping_host(host, count=4):
    """
    Ping 4 paquets vers un hôte ou une IP.
    Retourne un dict avec min/avg/max en ms, ou ok=False si injoignable.
    """
    try:
        out = subprocess.check_output(
            ["ping", "-c", str(count), "-W", "3", host],
            stderr=subprocess.DEVNULL, text=True
        )
        for line in out.splitlines():
            if "min/avg/max" in line:
                p = line.split("=")[1].strip().split("/")
                return {"host": host, "min": float(p[0]),
                        "avg": float(p[1]), "max": float(p[2].split()[0]), "ok": True}
        return {"host": host, "ok": False}
    except Exception:
        return {"host": host, "ok": False}


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD — API, DMs, envoi, export
# ─────────────────────────────────────────────────────────────────────────────

def discord_get(path, token):
    """GET simple sur l'API Discord v10. Lève une exception si ça plante."""
    import urllib.request
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        headers={"Authorization": token, "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def fetch_dms(token):
    """
    Récupère les 15 conversations DM les plus récentes.
    Pour chaque conv on prend le dernier message et l'ID de son auteur,
    ce qui permet de savoir si tu as répondu ou non.
    """
    if not token:
        return []
    try:
        channels = discord_get("/users/@me/channels", token)
        # On garde les DMs directs (type 1) qui ont au moins un message
        dms = [c for c in channels if c.get("type") == 1 and c.get("last_message_id")]
        # Tri par last_message_id décroissant — les snowflakes sont chronologiques
        dms.sort(key=lambda x: int(x.get("last_message_id", "0")), reverse=True)

        result = []
        for dm in dms[:15]:
            uname     = dm["recipients"][0]["username"] if dm.get("recipients") else "?"
            uid       = dm["recipients"][0]["id"]       if dm.get("recipients") else "0"
            cid       = dm["id"]
            try:
                msgs = discord_get(f"/channels/{cid}/messages?limit=1", token)
                if msgs:
                    m = msgs[0]
                    result.append({
                        "channel_id": cid,
                        "with":       uname,
                        "with_id":    uid,
                        "author":     m["author"]["username"],
                        "author_id":  m["author"]["id"],
                        "content":    (m.get("content") or "[media/embed]").replace("\n", " ")[:70],
                        "date":       m.get("timestamp", "")[:10],
                    })
            except Exception:
                result.append({"channel_id": cid, "with": uname, "with_id": uid,
                                "author": "?", "author_id": "0", "content": "?", "date": "?"})
        return result
    except Exception as e:
        return [{"channel_id": "", "with": f"Erreur: {e}", "with_id": "0",
                 "author": "", "author_id": "0", "content": "", "date": ""}]


def send_message(token, channel_id, message, file_path=None):
    """
    Envoie un message texte, ou un fichier (image, vidéo, pdf...) avec légende optionnelle.
    Pour les fichiers on utilise multipart/form-data comme un vrai client Discord.
    """
    import urllib.request, urllib.error, mimetypes
    url  = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    CRLF = b"\r\n"
    try:
        if file_path:
            fp   = Path(file_path).expanduser()
            if not fp.exists():
                return False, f"Fichier introuvable : {fp}"
            mime     = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            boundary = "MattDashBound7MA4YWxk"
            body     = b""
            # Part 1 : le texte du message en JSON
            body += (f"--{boundary}").encode() + CRLF
            body += b'Content-Disposition: form-data; name="payload_json"' + CRLF
            body += b"Content-Type: application/json" + CRLF + CRLF
            body += json.dumps({"content": message or ""}).encode() + CRLF
            # Part 2 : le fichier
            body += (f"--{boundary}").encode() + CRLF
            body += f'Content-Disposition: form-data; name="files[0]"; filename="{fp.name}"'.encode() + CRLF
            body += f"Content-Type: {mime}".encode() + CRLF + CRLF
            body += fp.read_bytes() + CRLF
            body += (f"--{boundary}--").encode() + CRLF
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": token,
                "Content-Type":  f"multipart/form-data; boundary={boundary}",
                "User-Agent":    "Mozilla/5.0",
            }, method="POST")
        else:
            # Message texte simple en JSON
            req = urllib.request.Request(url,
                data=json.dumps({"content": message}).encode(),
                headers={"Authorization": token, "Content-Type": "application/json",
                         "User-Agent": "Mozilla/5.0"}, method="POST")

        with urllib.request.urlopen(req, timeout=30) as r:
            return True, json.loads(r.read().decode()).get("id", "?")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            msg = json.loads(raw).get("message", raw)
        except Exception:
            msg = raw
        return False, msg
    except Exception as e:
        return False, str(e)


def get_channel_messages(token, channel_id, limit):
    """
    Télécharge les messages d'un channel par batchs de 100 (limite API Discord).
    limit = int ou 'all'. Retourne (liste_triée, erreur_ou_None).
    """
    all_msgs = []
    before   = None
    max_msgs = 999999 if limit == "all" else int(limit)

    while True:
        path = f"/channels/{channel_id}/messages?limit=100"
        if before:
            path += f"&before={before}"
        try:
            msgs = discord_get(path, token)
        except Exception as e:
            return all_msgs, str(e)
        if not msgs:
            break
        all_msgs.extend(msgs)
        if len(all_msgs) >= max_msgs or len(msgs) < 100:
            break
        before = msgs[-1]["id"]
        time.sleep(0.4)  # on respecte le rate limit Discord

    all_msgs = all_msgs[:max_msgs]
    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return all_msgs, None


def get_channel_info(token, channel_id):
    """
    Récupère les métadonnées du channel : nom, type, topic, serveur.
    Si c'est un salon de serveur (type 0), récupère aussi les membres
    pour la sidebar de l'export HTML.
    """
    try:
        info = discord_get(f"/channels/{channel_id}", token)
        result = {
            "name":       info.get("name", ""),
            "type":       info.get("type", 1),  # 0=serveur, 1=DM
            "guild_id":   info.get("guild_id", ""),
            "topic":      info.get("topic", ""),
            "members":    [],
            "guild_name": "",
        }
        if result["type"] == 0 and result["guild_id"]:
            try:
                members = discord_get(f"/guilds/{result['guild_id']}/members?limit=100", token)
                # On vire les bots, on garde les humains avec leur pseudo de serveur
                result["members"] = [
                    {"username": m["user"]["username"],
                     "nick":     m.get("nick") or m["user"]["username"],
                     "id":       m["user"]["id"]}
                    for m in members if not m["user"].get("bot", False)
                ]
            except Exception:
                pass
            try:
                result["guild_name"] = discord_get(f"/guilds/{result['guild_id']}", token).get("name", "")
            except Exception:
                pass
        return result
    except Exception:
        return {"name": "", "type": 1, "guild_id": "", "topic": "", "members": [], "guild_name": ""}


# ─────────────────────────────────────────────────────────────────────────────
# MARKDOWN DISCORD → HTML
# ─────────────────────────────────────────────────────────────────────────────

def discord_md_to_html(text):
    """
    Convertit le markdown Discord en HTML propre.

    Supporte : **gras** *italique* __souligné__ ~~barré~~ `code` ```bloc```
               -# sous-texte  # ## ### titres  > citation  ||spoiler||
               <@id> <#id> <@&id> mentions   <:emoji:id>  https:// liens auto
    """
    t = html_mod.escape(text)

    # Blocs de code d'abord (évite de re-formater leur contenu)
    t = re.sub(r'```(\w*)\n?(.*?)```',
               lambda m: f'<pre><code class="lang-{m.group(1)}">{m.group(2).strip()}</code></pre>',
               t, flags=re.DOTALL)

    # -# sous-texte discret (feature Discord récente)
    t = re.sub(r'^-# (.+)$', r'<span class="subtext">\1</span>', t, flags=re.MULTILINE)

    # Titres Discord (### ## #)
    t = re.sub(r'^### (.+)$', r'<h3>\1</h3>', t, flags=re.MULTILINE)
    t = re.sub(r'^## (.+)$',  r'<h2>\1</h2>', t, flags=re.MULTILINE)
    t = re.sub(r'^# (.+)$',   r'<h1>\1</h1>', t, flags=re.MULTILINE)

    # Citations — &gt; parce que html.escape a déjà tourné
    t = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', t, flags=re.MULTILINE)

    # Gras+italique ***texte*** — avant gras seul sinon conflit
    t = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', t)
    # Gras **texte**
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    # Souligné __texte__ — avant _ital_ pour éviter les conflits
    t = re.sub(r'__(.+?)__', r'<u>\1</u>', t)
    # Italique *texte* ou _texte_
    t = re.sub(r'\*([^*\n]+?)\*', r'<em>\1</em>', t)
    t = re.sub(r'_([^_\n]+?)_',   r'<em>\1</em>', t)
    # Barré ~~texte~~
    t = re.sub(r'~~(.+?)~~', r'<s>\1</s>', t)
    # Code inline `texte`
    t = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', t)
    # Spoiler ||texte||
    t = re.sub(r'\|\|(.+?)\|\|', r'<span class="spoiler">\1</span>', t)

    # Mentions Discord (html.escape a transformé < en &lt; etc.)
    t = re.sub(r'&lt;@!?(\d+)&gt;',    r'<span class="mention">@\1</span>', t)
    t = re.sub(r'&lt;#(\d+)&gt;',       r'<span class="mention">#\1</span>', t)
    t = re.sub(r'&lt;@&amp;(\d+)&gt;',  r'<span class="mention">@rôle</span>', t)
    t = re.sub(r'&lt;a?:(\w+):\d+&gt;', r'<span class="emoji">:\1:</span>', t)

    # Liens https automatiques
    t = re.sub(r'(https?://[^\s<>"&]+)',
               r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)

    t = t.replace("\n", "<br>")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT HTML
# ─────────────────────────────────────────────────────────────────────────────

def export_html(messages, channel_id, outfile, channel_info=None):
    """
    Génère une transcription HTML complète d'un channel Discord.

    Inclut :
    - Markdown Discord complet (**gras** *ital* -# ## spoiler etc.)
    - Images en miniatures cliquables avec lightbox JS
    - Vidéos avec lecteur intégré, fichiers avec lien téléchargement
    - Stickers, emojis custom, réactions avec compteur
    - Embeds avec couleur et image
    - Messages cités (réponses) avec lien vers le message d'origine
    - Sidebar membres si salon de serveur (type 0)
    - Barre de recherche temps réel
    - Spoilers révélables au clic
    """
    if channel_info is None:
        channel_info = {}

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg"}
    VIDEO_EXTS = {".mp4", ".webm", ".mov", ".ogg"}

    def fmt_ts(ts):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return ts[:16] if ts else "?"

    def avatar_url(user):
        uid = user.get("id", "0")
        av  = user.get("avatar")
        if av:
            return f"https://cdn.discordapp.com/avatars/{uid}/{av}.png?size=32"
        return f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"

    def msg_url(msg):
        guild = msg.get("guild_id") or channel_info.get("guild_id", "")
        ch    = msg.get("channel_id", channel_id)
        mid   = msg.get("id", "0")
        base  = f"https://discord.com/channels/{guild}" if guild else "https://discord.com/channels/@me"
        return f"{base}/{ch}/{mid}"

    # ── Construction des messages ─────────────────────────────────────────────
    rows = []
    for m in messages:
        author       = m.get("author", {})
        uname        = html_mod.escape(author.get("username", "?"))
        raw          = m.get("content", "") or ""
        content_html = discord_md_to_html(raw) if raw else ""
        attachments  = m.get("attachments",   [])
        embeds       = m.get("embeds",        [])
        stickers     = m.get("sticker_items", [])
        reactions    = m.get("reactions",     [])
        ref_msg      = m.get("referenced_message")  # message cité dans une réponse
        media_html   = ""

        # Message cité (reply Discord)
        if ref_msg:
            ra  = html_mod.escape(ref_msg.get("author", {}).get("username", "?"))
            rc  = html_mod.escape((ref_msg.get("content") or "[media]")[:80])
            rid = ref_msg.get("id", "")
            media_html += (f'<div class="reply">'
                           f'<span class="reply-author">↩ {ra}</span>'
                           f'<span class="reply-content">{rc}</span>'
                           f'<a href="#m{rid}" class="reply-link">↗</a></div>')

        # Pièces jointes
        for att in attachments:
            url_a = att.get("url", "")
            fname = html_mod.escape(att.get("filename", ""))
            ext   = Path(att.get("filename", "")).suffix.lower()
            w     = att.get("width", 0)
            if ext in IMAGE_EXTS:
                sty = f' style="max-width:min(320px,{w}px)"' if w else ""
                media_html += (f'<a href="{url_a}" target="_blank" class="img-link">'
                               f'<img class="att-img" src="{url_a}" alt="{fname}"{sty} loading="lazy"></a>')
            elif ext in VIDEO_EXTS:
                media_html += f'<video class="att-vid" src="{url_a}" controls></video>'
            else:
                sz  = att.get("size", 0)
                szs = f"{sz // 1024}Ko" if sz > 1024 else f"{sz}o"
                media_html += (f'<a class="att-file" href="{url_a}" target="_blank">'
                               f'📎 {fname} <span class="att-size">({szs})</span></a>')

        # Embeds (liens prévisualisés, cartes riches)
        for emb in embeds:
            img   = emb.get("image") or emb.get("thumbnail")
            color = f'#{emb.get("color", 0):06x}' if emb.get("color") else "#2a2a3a"
            media_html += f'<div class="embed" style="border-left-color:{color}">'
            if emb.get("title"):
                et = html_mod.escape(emb["title"])
                eu = emb.get("url", "")
                media_html += f'<div class="embed-title">' + (
                    f'<a href="{eu}" target="_blank">{et}</a>' if eu else et) + '</div>'
            if emb.get("description"):
                media_html += f'<div class="embed-desc">{discord_md_to_html(emb["description"][:300])}</div>'
            if img and img.get("url"):
                iu = img["url"]
                media_html += (f'<a href="{iu}" target="_blank" class="img-link">'
                               f'<img class="att-img" src="{iu}" loading="lazy"></a>')
            media_html += '</div>'

        # Stickers Discord
        for st in stickers:
            sid   = st.get("id", "")
            sname = html_mod.escape(st.get("name", "sticker"))
            if st.get("format_type", 1) in (1, 2):  # PNG ou APNG
                surl = f"https://media.discordapp.net/stickers/{sid}.png?size=128"
                media_html += f'<img class="att-img sticker" src="{surl}" alt="{sname}" title=":{sname}:" loading="lazy">'

        # Réactions emoji
        rxns_html = "".join(
            f'<span class="reaction{"reaction-me" if r.get("me") else ""}">'
            f'{r.get("emoji",{}).get("name","?")} {r.get("count",0)}</span>'
            for r in reactions
        )

        if not content_html and not media_html:
            content_html = '<span class="empty">[vide]</span>'

        ts  = fmt_ts(m.get("timestamp", ""))
        av  = avatar_url(author)
        lnk = msg_url(m)
        mid = m.get("id", "")

        rows.append(
            f'<div class="msg" id="m{mid}">'
            f'<img class="av" src="{av}" onerror="this.src=\'https://cdn.discordapp.com/embed/avatars/0.png\'">'
            f'<div class="body">'
            f'<span class="author">{uname}</span><span class="ts">{ts}</span>'
            f'<a class="lnk" href="{lnk}" target="_blank" title="Ouvrir dans Discord">↗</a>'
            f'<div class="ct">{content_html}</div>'
            + (f'<div class="media">{media_html}</div>' if media_html else "")
            + (f'<div class="reactions">{rxns_html}</div>' if rxns_html else "")
            + '</div></div>'
        )

    # ── Sidebar membres (salons de serveur uniquement) ────────────────────────
    is_server = channel_info.get("type", 1) == 0
    members   = channel_info.get("members", [])
    sidebar   = ""
    if is_server and members:
        items = "".join(
            f'<div class="member">'
            f'<span class="m-av">{html_mod.escape(m["nick"])[0].upper()}</span>'
            f'<span class="m-name">{html_mod.escape(m["nick"])}</span>'
            f'</div>'
            for m in sorted(members, key=lambda x: x["nick"].lower())
        )
        ch_name  = html_mod.escape(channel_info.get("name", channel_id))
        g_name   = html_mod.escape(channel_info.get("guild_name", ""))
        ch_topic = html_mod.escape(channel_info.get("topic", "") or "")
        sidebar  = (
            f'<aside id="sidebar">'
            f'<div class="sb-header">'
            f'<div class="sb-guild">{g_name}</div>'
            f'<div class="sb-channel">#{ch_name}</div>'
            + (f'<div class="sb-topic">{ch_topic}</div>' if ch_topic else "")
            + f'</div>'
            f'<div class="sb-label">Membres ({len(members)})</div>'
            f'<div class="sb-members">{items}</div>'
            f'</aside>'
        )

    # ── Titre de la page ──────────────────────────────────────────────────────
    g_name_raw  = channel_info.get("guild_name", "")
    ch_name_raw = channel_info.get("name", "")
    page_title  = f"#{ch_name_raw}" if ch_name_raw else channel_id
    if g_name_raw:
        page_title = f"{g_name_raw} — {page_title}"

    h1_label = (f'#{html_mod.escape(ch_name_raw)}' if ch_name_raw else f'📋 {channel_id}')
    h1_meta  = f'<span class="meta">{html_mod.escape(g_name_raw)}</span>' if g_name_raw else ""

    # ── Page HTML finale ──────────────────────────────────────────────────────
    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html_mod.escape(page_title)} — {len(messages)} msgs</title>
<style>
/* reset basique */
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0d12;color:#cdd6f4;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:1.5;display:flex;flex-direction:column;height:100vh}}

/* header fixe en haut */
header{{position:sticky;top:0;z-index:20;background:#13131c;border-bottom:1px solid #232336;padding:9px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0}}
header h1{{font-size:14px;color:#89b4fa;font-weight:700;letter-spacing:.3px}}
.meta{{color:#585b70;font-size:11px}}
#q{{margin-left:auto;background:#1e1e2e;border:1px solid #313244;color:#cdd6f4;padding:5px 11px;border-radius:4px;font:inherit;font-size:12px;width:220px;outline:none}}
#q:focus{{border-color:#89b4fa}}

/* layout : messages + sidebar optionnelle */
.layout{{display:flex;flex:1;overflow:hidden}}
.msgs-wrap{{flex:1;overflow-y:auto;padding:10px 18px}}
.cnt{{color:#45475a;font-size:11px;padding:3px 0 8px}}

/* sidebar membres */
aside#sidebar{{width:200px;flex-shrink:0;background:#111118;border-left:1px solid #1e1e2e;overflow-y:auto;padding:12px 10px}}
.sb-header{{margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #1e1e2e}}
.sb-guild{{color:#89b4fa;font-weight:700;font-size:13px}}
.sb-channel{{color:#a6adc8;font-size:12px;margin-top:2px}}
.sb-topic{{color:#585b70;font-size:11px;margin-top:4px;font-style:italic}}
.sb-label{{color:#45475a;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px}}
.member{{display:flex;align-items:center;gap:7px;padding:4px;border-radius:4px}}
.member:hover{{background:#1e1e2e}}
.m-av{{width:26px;height:26px;border-radius:50%;background:#3b4252;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0}}
.m-name{{font-size:13px;color:#a6adc8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}

/* messages */
.msg{{display:flex;gap:10px;padding:5px 7px;border-radius:4px;border-left:2px solid transparent;transition:background .1s,border-color .1s}}
.msg:hover{{background:#15151e;border-left-color:#89b4fa}}
.msg.h{{display:none}}
.av{{width:32px;height:32px;border-radius:50%;flex-shrink:0;margin-top:2px;background:#232336}}
.body{{flex:1;min-width:0}}
.author{{color:#89b4fa;font-weight:700;font-size:14px}}
.ts{{color:#45475a;font-size:11px;margin-left:8px}}
.lnk{{color:#2a2a3a;font-size:11px;margin-left:5px;text-decoration:none;transition:color .1s}}
.lnk:hover{{color:#89b4fa}}
.ct{{color:#cdd6f4;margin-top:2px;word-break:break-word}}

/* formatage markdown discord */
.ct strong{{color:#fff;font-weight:700}}
.ct em{{font-style:italic;color:#d4d4e8}}
.ct u{{text-decoration:underline}}
.ct s{{text-decoration:line-through;color:#6b7280}}
.ct code{{background:#1e1e2e;color:#a6e3a1;padding:1px 5px;border-radius:3px;font-family:'Courier New',monospace;font-size:12px}}
.ct pre{{background:#1e1e2e;padding:10px 14px;border-radius:6px;overflow-x:auto;margin-top:6px}}
.ct pre code{{background:none;padding:0;color:#cdd6f4;font-size:12px}}
.ct blockquote{{border-left:3px solid #4a4a6a;padding-left:10px;color:#a6adc8;font-style:italic;margin-top:4px}}
.ct h1{{font-size:18px;color:#89b4fa;margin:6px 0 3px}}
.ct h2{{font-size:16px;color:#89b4fa;margin:5px 0 2px}}
.ct h3{{font-size:14px;color:#89b4fa;margin:4px 0 2px}}
.subtext{{font-size:11px;color:#585b70}}
.spoiler{{background:#2a2a3a;color:transparent;border-radius:3px;cursor:pointer;padding:0 3px;transition:color .2s;user-select:none}}
.spoiler.revealed{{color:#cdd6f4}}
.mention{{background:#3d4163;color:#a5b4fc;border-radius:3px;padding:0 3px;font-size:13px}}
.emoji{{font-size:12px;color:#a6adc8}}
.ct a{{color:#89b4fa;text-decoration:none}}
.ct a:hover{{text-decoration:underline}}

/* reply (message cité) */
.reply{{display:flex;align-items:center;gap:8px;background:#12121a;border-left:2px solid #4a4a6a;padding:3px 8px;border-radius:3px;margin-bottom:4px;font-size:12px;color:#6b7280}}
.reply-author{{color:#89b4fa;font-weight:600;flex-shrink:0}}
.reply-content{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}}
.reply-link{{color:#4a4a6a;text-decoration:none;margin-left:auto;flex-shrink:0}}
.reply-link:hover{{color:#89b4fa}}

/* médias */
.media{{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:flex-start}}
.att-img{{max-width:320px;max-height:240px;border-radius:5px;border:1px solid #232336;cursor:zoom-in;transition:opacity .15s;display:block}}
.att-img:hover{{opacity:.85}}
.att-img.sticker{{max-width:96px;max-height:96px;border:none;background:transparent;cursor:default}}
.att-vid{{max-width:360px;border-radius:5px;border:1px solid #232336;display:block}}
.att-file{{display:inline-flex;align-items:center;gap:5px;background:#1e1e2e;border:1px solid #313244;border-radius:4px;padding:4px 10px;color:#89b4fa;text-decoration:none;font-size:12px}}
.att-file:hover{{border-color:#89b4fa}}
.att-size{{color:#45475a;font-size:10px}}

/* embeds */
.embed{{border-left:3px solid #5865f2;background:#1a1a24;border-radius:0 4px 4px 0;padding:8px 12px;margin-top:4px;max-width:440px}}
.embed-title{{font-weight:600;color:#89b4fa;margin-bottom:4px;font-size:13px}}
.embed-title a{{color:#89b4fa;text-decoration:none}}
.embed-title a:hover{{text-decoration:underline}}
.embed-desc{{font-size:12px;color:#a6adc8}}

/* réactions */
.reactions{{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}}
.reaction{{background:#1e1e2e;border:1px solid #313244;border-radius:12px;padding:2px 8px;font-size:12px}}
.reaction-me{{border-color:#89b4fa;background:#1e2a3e}}

/* misc */
.empty{{color:#45475a;font-style:italic;font-size:12px}}
::-webkit-scrollbar{{width:5px}}
::-webkit-scrollbar-track{{background:#0d0d12}}
::-webkit-scrollbar-thumb{{background:#232336;border-radius:3px}}
::-webkit-scrollbar-thumb:hover{{background:#3a3a4a}}

/* lightbox overlay */
#lightbox{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:999;align-items:center;justify-content:center;cursor:zoom-out}}
#lightbox.active{{display:flex}}
#lightbox img{{max-width:92vw;max-height:92vh;border-radius:6px;box-shadow:0 0 60px rgba(0,0,0,.8)}}
</style>
</head>
<body>
<header>
  <h1>{h1_label}</h1>
  {h1_meta}
  <span class="meta">{len(messages)} messages — exporté le {datetime.now().strftime('%d/%m/%Y %H:%M')}</span>
  <input id="q" placeholder="🔍 Rechercher..." oninput="filter(this.value)">
</header>
<div class="layout">
  <div class="msgs-wrap">
    <div class="cnt" id="cnt">{len(messages)} messages</div>
    {"".join(rows)}
  </div>
  {sidebar}
</div>

<!-- lightbox pour les images -->
<div id="lightbox"><img id="lb-img" src="" alt=""></div>

<script>
// Recherche en temps réel
function filter(q) {{
  q = q.toLowerCase();
  let v = 0;
  document.querySelectorAll('.msg').forEach(e => {{
    const ok = !q || e.textContent.toLowerCase().includes(q);
    e.classList.toggle('h', !ok);
    if (ok) v++;
  }});
  document.getElementById('cnt').textContent = v + ' messages';
}}

// Lightbox : clic sur une image = plein écran
const lb = document.getElementById('lightbox');
const lbImg = document.getElementById('lb-img');
document.querySelectorAll('.img-link').forEach(a => {{
  a.addEventListener('click', e => {{
    e.preventDefault();
    lbImg.src = a.href;
    lb.classList.add('active');
  }});
}});
lb.addEventListener('click', () => lb.classList.remove('active'));
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') lb.classList.remove('active'); }});

// Spoilers révélables au clic
document.querySelectorAll('.spoiler').forEach(el => {{
  el.addEventListener('click', () => el.classList.toggle('revealed'));
}});

// Scroll jusqu'au message cité quand on clique sur ↗ dans un reply
document.querySelectorAll('.reply-link').forEach(a => {{
  a.addEventListener('click', e => {{
    e.preventDefault();
    const target = document.querySelector(a.getAttribute('href'));
    if (target) {{
      target.scrollIntoView({{behavior: 'smooth', block: 'center'}});
      target.style.background = '#1e2a1e';
      setTimeout(() => target.style.background = '', 1200);
    }}
  }});
}});
</script>
</body></html>"""

    outfile.parent.mkdir(parents=True, exist_ok=True)
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(page)


# ─────────────────────────────────────────────────────────────────────────────
# TUI CURSES — l'interface graphique dans le terminal
# ─────────────────────────────────────────────────────────────────────────────

class MattDash:
    def __init__(self, stdscr):
        self.scr     = stdscr
        self.cfg     = load_config()
        self.running = True

        # Données partagées entre threads (protégées par self.lock)
        self.stats         = {}
        self.weather       = "Chargement météo..."
        self.dms           = []
        self.console_lines = []   # liste de (texte, attribut curses)
        self.console_input = ""
        self.input_cursor  = 0
        self.lock          = threading.Lock()

        # Init curses propre
        curses.start_color()
        curses.use_default_colors()
        curses.curs_set(0)          # on cache le vrai curseur
        self.scr.nodelay(True)
        self.scr.keypad(True)

        # Paires de couleurs (indice, fg, bg=-1 = transparent)
        curses.init_pair(1, curses.COLOR_CYAN,    -1)
        curses.init_pair(2, curses.COLOR_GREEN,   -1)
        curses.init_pair(3, curses.COLOR_YELLOW,  -1)
        curses.init_pair(4, curses.COLOR_RED,     -1)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        curses.init_pair(6, curses.COLOR_BLUE,    -1)
        curses.init_pair(7, curses.COLOR_WHITE,   -1)
        curses.init_pair(8, 8,                    -1)

        self.C_CYAN    = curses.color_pair(1)
        self.C_GREEN   = curses.color_pair(2)
        self.C_YELLOW  = curses.color_pair(3)
        self.C_RED     = curses.color_pair(4)
        self.C_MAGENTA = curses.color_pair(5)
        self.C_BLUE    = curses.color_pair(6)
        self.C_WHITE   = curses.color_pair(7)
        self.C_DIM     = curses.color_pair(8)

        # Lance les threads de fond
        threading.Thread(target=self._stats_loop,   daemon=True).start()
        threading.Thread(target=self._weather_loop, daemon=True).start()
        threading.Thread(target=self._dms_loop,     daemon=True).start()

    # ── Threads de mise à jour ────────────────────────────────────────────────

    def _stats_loop(self):
        """Rafraîchit les stats système toutes les secondes."""
        while self.running:
            cpu                          = get_cpu()
            ru, rt, rp                   = get_ram()
            du, dt, dp                   = get_disk()
            with self.lock:
                self.stats = {
                    "cpu": cpu, "ram_used": ru, "ram_total": rt, "ram_pct": rp,
                    "disk_used": du, "disk_total": dt, "disk_pct": dp,
                    "uptime": get_uptime(), "load": get_load(), "ip": get_local_ip(),
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            time.sleep(1)

    def _weather_loop(self):
        """Rafraîchit la météo toutes les 5 minutes. Ville depuis la config = variable."""
        while self.running:
            city = self.cfg.get("weather_city", DEFAULT_CONFIG["weather_city"])
            w    = fetch_weather(city)
            with self.lock:
                self.weather = w
            time.sleep(300)

    def _dms_loop(self):
        """Rafraîchit les DMs selon dm_refresh_interval (défaut 60s)."""
        while self.running:
            token = self.cfg.get("discord_token", "")
            dms   = fetch_dms(token)
            with self.lock:
                self.dms = dms
            time.sleep(self.cfg.get("dm_refresh_interval", 60))

    # ── Helpers d'affichage ───────────────────────────────────────────────────

    def _addstr(self, y, x, text, attr=0):
        """Écrit du texte en gérant les débordements hors de l'écran."""
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        max_len = w - x - 1
        if max_len <= 0:
            return
        try:
            self.scr.addstr(y, x, str(text)[:max_len], attr)
        except curses.error:
            pass

    def _hline(self, y, char="─", label="", attr=None):
        """Ligne horizontale de séparation avec label centré optionnel."""
        if attr is None:
            attr = self.C_BLUE | curses.A_BOLD
        _, w = self.scr.getmaxyx()
        if label:
            lbl  = f" {label} "
            side = (w - len(lbl)) // 2
            line = char * side + lbl + char * (w - side - len(lbl))
        else:
            line = char * (w - 1)
        self._addstr(y, 0, line, attr)

    def _bar(self, pct, width):
        """Barre de progression ASCII '████░░░░' pour la largeur donnée."""
        fill = int(pct / 100 * width)
        return "█" * fill + "░" * (width - fill)

    def _bar_attr(self, pct):
        """Couleur de la barre : vert < 70%, jaune < 90%, rouge au-dessus."""
        if pct > 90:
            return self.C_RED
        if pct > 70:
            return self.C_YELLOW
        return self.C_GREEN

    # ── Dessin des trois zones ────────────────────────────────────────────────

    def _draw_stats(self, y0, w):
        """Zone du haut : stats système avec barres de progression colorées."""
        s = self.stats
        if not s:
            self._addstr(y0, 2, "Chargement stats...", self.C_DIM)
            return
        bw = max(8, w - 30)
        self._hline(y0, "─", f"SYSTÈME  {s['time']}")
        # Uptime et IP sur la même ligne pour économiser de l'espace
        self._addstr(y0+1, 2,        "⏱ Uptime:",  self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+1, 13,       s["uptime"],   self.C_WHITE)
        self._addstr(y0+1, w//2,     "🌐 IP:",      self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+1, w//2+7,   s["ip"],       self.C_WHITE)
        # CPU
        self._addstr(y0+2, 2, "🔲 CPU:   ", self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+2, 12, self._bar(s["cpu"], bw), self._bar_attr(s["cpu"]))
        self._addstr(y0+2, 13+bw, f'{s["cpu"]:.1f}%', self.C_WHITE | curses.A_BOLD)
        # RAM
        self._addstr(y0+3, 2, "💾 RAM:   ", self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+3, 12, self._bar(s["ram_pct"], bw), self._bar_attr(s["ram_pct"]))
        self._addstr(y0+3, 13+bw, f'{s["ram_used"]}M/{s["ram_total"]}M ({s["ram_pct"]:.0f}%)', self.C_WHITE)
        # Disque
        self._addstr(y0+4, 2, "🗄 Disque:", self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+4, 12, self._bar(s["disk_pct"], bw), self._bar_attr(s["disk_pct"]))
        self._addstr(y0+4, 13+bw, f'{s["disk_used"]}G/{s["disk_total"]}G ({s["disk_pct"]:.0f}%)', self.C_WHITE)
        # Load average
        l1, l5, l15 = s["load"]
        self._addstr(y0+5, 2, "📊 Load:  ", self.C_CYAN | curses.A_BOLD)
        self._addstr(y0+5, 12, f"1m:{l1}  5m:{l5}  15m:{l15}", self.C_WHITE)

    def _draw_middle(self, y0, y1, w):
        """Zone du milieu : météo + 15 derniers DMs.
        Les messages non-répondus (dernier msg pas de toi) sont en gras avec ●."""
        self._hline(y0, "─", "MÉTÉO & DMs DISCORD")
        self._addstr(y0+1, 2, "🌤 ", self.C_YELLOW | curses.A_BOLD)
        self._addstr(y0+1, 5, self.weather[:w-6], self.C_WHITE)
        if y0+2 < y1:
            self._addstr(y0+2, 2, "Derniers messages :", self.C_BLUE | curses.A_BOLD)

        my_id  = self.cfg.get("my_discord_id", "")
        dm_row = y0 + 3

        if not self.dms:
            if dm_row < y1:
                msg = ("Token non configuré — tape : config token <token>"
                       if not self.cfg.get("discord_token") else "Chargement DMs...")
                self._addstr(dm_row, 4, msg, self.C_DIM)
            return

        for i, dm in enumerate(self.dms):
            r = dm_row + i
            if r >= y1:
                break
            with_name = dm.get("with",      "?")
            author    = dm.get("author",    "?")
            author_id = dm.get("author_id", "0")
            content   = dm.get("content",   "")
            date      = dm.get("date",      "")

            # C'est non-répondu si le dernier message n'est pas de toi
            # On compare l'ID si on le connait, sinon on ne peut pas savoir
            not_mine = (my_id and author_id != my_id)

            # Marqueur visuel : ● rouge si non-répondu, · gris sinon
            self._addstr(r, 2, "●" if not_mine else "·",
                         self.C_RED if not_mine else self.C_DIM)

            name_attr    = self.C_MAGENTA | curses.A_BOLD
            content_attr = (self.C_WHITE | curses.A_BOLD) if not_mine else self.C_DIM

            self._addstr(r, 4, f"@{with_name}", name_attr)
            off = 5 + len(with_name)
            self._addstr(r, off, f" [{date}]", self.C_DIM)
            off += len(date) + 3
            self._addstr(r, off, f" {author}: ", self.C_CYAN)
            off += len(author) + 3
            self._addstr(r, off, content[:max(0, w - off - 2)], content_attr)

    def _draw_console(self, y0, y1, w):
        """Zone du bas (1/4) : console interactive avec historique et ligne d'input."""
        self._hline(y0, "═", "CONSOLE — tape 'help' pour l'aide")

        # Affichage des lignes de sortie, scrollé vers le bas automatiquement
        out_start    = y0 + 1
        out_end      = y1 - 1
        visible      = out_end - out_start
        lines        = self.console_lines
        start        = max(0, len(lines) - visible)
        for i, (text, attr) in enumerate(lines[start:]):
            r = out_start + i
            if r >= out_end:
                break
            self._addstr(r, 2, text[:w-3], attr)

        # Ligne d'input avec curseur visuel (caractère inversé)
        prompt = "❯ "
        input_row = y1 - 1
        self._addstr(input_row, 0, prompt, self.C_CYAN | curses.A_BOLD)
        self._addstr(input_row, len(prompt),
                     self.console_input[:w - len(prompt) - 2],
                     self.C_WHITE | curses.A_BOLD)
        cx = len(prompt) + self.input_cursor
        if cx < w - 1:
            ch = self.console_input[self.input_cursor] if self.input_cursor < len(self.console_input) else " "
            try:
                self.scr.addch(input_row, cx, ch, self.C_WHITE | curses.A_REVERSE)
            except curses.error:
                pass

    def draw(self):
        """Redessine tout l'écran. ~10 fps, thread-safe via self.lock."""
        h, w = self.scr.getmaxyx()
        self.scr.erase()
        stats_h      = 7
        console_h    = max(8, h // 4)
        console_top  = h - console_h
        with self.lock:
            self._draw_stats(0, w)
            self._draw_middle(stats_h, console_top, w)
            self._draw_console(console_top, h, w)
        self.scr.noutrefresh()
        curses.doupdate()

    # ── Console : log + exécution de commandes ────────────────────────────────

    def log(self, text, attr=None):
        """Ajoute une ligne dans la console. Max 500 lignes en mémoire."""
        if attr is None:
            attr = self.C_WHITE
        with self.lock:
            self.console_lines.append((text, attr))
            if len(self.console_lines) > 500:
                self.console_lines = self.console_lines[-500:]

    def exec_command(self, line):
        """Parse et exécute une commande. Les ops réseau tournent dans des threads séparés."""
        line = line.strip()
        if not line:
            return
        parts = line.split(" ", 1)
        cmd   = parts[0].lower()
        rest  = parts[1] if len(parts) > 1 else ""

        if cmd == "send":
            # send <channel_id> <message>
            # send <channel_id> file:/chemin/image.png [légende optionnelle]
            sub = rest.split(" ", 1)
            if not sub or not sub[0]:
                self.log("Usage : send <id> <message>  |  send <id> file:/chemin [légende]", self.C_RED)
                return
            cid   = sub[0]
            rest2 = sub[1] if len(sub) > 1 else ""
            token = self.cfg.get("discord_token", "")
            if not token:
                self.log("✗ Token non configuré — tape : config token <ton_token>", self.C_RED)
                return
            # Détection de file:/chemin n'importe où dans le reste
            file_path = None
            msg_text  = rest2
            fm = re.search(r'file:(\S+)', rest2)
            if fm:
                file_path = fm.group(1)
                msg_text  = re.sub(r'file:\S+', '', rest2).strip()
            if not file_path and not msg_text:
                self.log("Usage : send <id> <message>  |  send <id> file:/chemin [légende]", self.C_RED)
                return
            label = f"fichier {Path(file_path).name}" if file_path else "message"
            self.log(f"⟳ Envoi {label} → {cid}...", self.C_DIM)
            def _send(tok=token, c=cid, m=msg_text, fp=file_path):
                try:
                    ok, info = send_message(tok, c, m, file_path=fp)
                    self.log(f"✓ Envoyé (id={info})" if ok else f"✗ {info}",
                             self.C_GREEN if ok else self.C_RED)
                except Exception as e:
                    self.log(f"✗ {e}", self.C_RED)
            threading.Thread(target=_send, daemon=True).start()

        elif cmd == "get":
            # get <channel_id> <nombre|all>
            sub   = rest.split(" ", 1)
            cid   = sub[0] if sub else ""
            count = sub[1].strip() if len(sub) > 1 else "50"
            if not cid:
                self.log("Usage : get <channel_id> <nombre|all>", self.C_RED)
                return
            token = self.cfg.get("discord_token", "")
            if not token:
                self.log("✗ Token non configuré", self.C_RED)
                return
            self.log(f"⟳ Export channel {cid} ({count} msgs)...", self.C_DIM)
            def _get():
                try:
                    self.log("⟳ Infos du channel...", self.C_DIM)
                    ch_info = get_channel_info(token, cid)
                    if ch_info.get("name"):
                        name = f"#{ch_info['name']}"
                        if ch_info.get("guild_name"):
                            name = f"{ch_info['guild_name']} {name}"
                        self.log(f"  → {name}", self.C_DIM)
                    if ch_info.get("members"):
                        self.log(f"  → {len(ch_info['members'])} membres", self.C_DIM)
                    msgs, err = get_channel_messages(token, cid, count)
                    if err:
                        self.log(f"✗ Erreur API : {err}", self.C_RED)
                        return
                    self.log(f"✓ {len(msgs)} messages. Génération HTML...", self.C_GREEN)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    for candidate in [LOG_DIR, Path.home() / "Documents" / "Log"]:
                        try:
                            candidate.mkdir(parents=True, exist_ok=True)
                            outfile = candidate / f"channel_{cid}_{ts}.html"
                            export_html(msgs, cid, outfile, ch_info)
                            self.log(f"✓ {outfile}", self.C_GREEN | curses.A_BOLD)
                            return
                        except PermissionError:
                            continue
                    self.log(f"✗ Permission refusée sur {LOG_DIR} — sudo chown $USER:$USER {LOG_DIR}", self.C_RED)
                except Exception as e:
                    self.log(f"✗ {e}", self.C_RED)
            threading.Thread(target=_get, daemon=True).start()

        elif cmd == "ping":
            host = rest.strip().split()[0] if rest.strip() else ""
            if not host:
                self.log("Usage : ping <host_ou_ip>", self.C_RED)
                return
            self.log(f"⟳ Ping {host} (4 paquets)...", self.C_DIM)
            def _ping():
                try:
                    r = ping_host(host)
                    if r["ok"]:
                        self.log(f"● {host}  min={r['min']:.1f}ms  avg={r['avg']:.1f}ms  max={r['max']:.1f}ms",
                                 self.C_GREEN)
                    else:
                        self.log(f"✗ {host} — injoignable ou DNS inconnu", self.C_RED)
                except Exception as e:
                    self.log(f"✗ {e}", self.C_RED)
            threading.Thread(target=_ping, daemon=True).start()

        elif cmd == "dms":
            self.log("⟳ Actualisation des DMs...", self.C_DIM)
            def _dms():
                dms = fetch_dms(self.cfg.get("discord_token", ""))
                with self.lock:
                    self.dms = dms
                self.log(f"✓ {len(dms)} conversations chargées", self.C_GREEN)
            threading.Thread(target=_dms, daemon=True).start()

        elif cmd == "weather":
            self.log("⟳ Actualisation météo...", self.C_DIM)
            def _w():
                city = self.cfg.get("weather_city", DEFAULT_CONFIG["weather_city"])
                w    = fetch_weather(city)
                with self.lock:
                    self.weather = w
                self.log(f"✓ {w}", self.C_GREEN)
            threading.Thread(target=_w, daemon=True).start()

        elif cmd == "config":
            sub = rest.split(" ", 1)
            key = sub[0] if sub else ""
            val = sub[1].strip() if len(sub) > 1 else ""
            key_map = {
                "token":    "discord_token",
                "city":     "weather_city",
                "myid":     "my_discord_id",
                "interval": "dm_refresh_interval",
            }
            if key in key_map and val:
                real_key = key_map[key]
                if key == "interval":
                    try:
                        val = int(val)
                    except ValueError:
                        self.log("✗ Valeur invalide (entier attendu)", self.C_RED)
                        return
                self.cfg[real_key] = val
                save_config(self.cfg)
                display = (val[:8] + "...") if key == "token" and len(str(val)) > 8 else val
                self.log(f"✓ {key} = {display}", self.C_GREEN)
                if key == "city":
                    self.log("  Tape 'weather' pour actualiser", self.C_DIM)
                if key == "myid":
                    self.log("  Les msgs non-répondus seront en gras", self.C_DIM)
            elif key == "show":
                token = self.cfg.get("discord_token", "")
                self.log(f"  token    = {token[:8] + '...' if len(token) > 8 else '(vide)'}", self.C_CYAN)
                self.log(f"  city     = {self.cfg.get('weather_city')}", self.C_CYAN)
                self.log(f"  myid     = {self.cfg.get('my_discord_id') or '(vide)'}", self.C_CYAN)
                self.log(f"  interval = {self.cfg.get('dm_refresh_interval')}s", self.C_CYAN)
                self.log(f"  fichier  = {CONFIG_FILE}", self.C_DIM)
            else:
                self.log("  config token <token>      Token Discord selfbot", self.C_DIM)
                self.log("  config city <ville,Pays>  Ville météo", self.C_DIM)
                self.log("  config myid <ton_id>      Ton ID Discord", self.C_DIM)
                self.log("  config interval <secs>    Fréquence refresh DMs", self.C_DIM)
                self.log("  config show               Voir la config", self.C_DIM)

        elif cmd == "clear":
            with self.lock:
                self.console_lines = []

        elif cmd in ("quit", "exit", "q"):
            self.running = False

        elif cmd == "help":
            # Aide complète organisée par sections
            sections = [
                ("MESSAGES DISCORD", [
                    ("send <id> <message>",             "Envoyer un DM texte (espaces OK)"),
                    ("send <id> file:/chemin [légende]","Envoyer une image ou un fichier"),
                    ("  ex: send 123 file:~/photo.png voilà !", ""),
                    ("get <id> <n|all>",                "Exporter un channel en HTML"),
                    ("  ex: get 123456789 100          ",""),
                    ("  ex: get 123456789 all          ","Export complet"),
                    ("dms",                             "Rafraîchir les 15 derniers DMs"),
                ]),
                ("RÉSEAU", [
                    ("ping <host>",                     "Latence min/avg/max en ms"),
                    ("  ex: ping 8.8.8.8               ",""),
                    ("  ex: ping google.com             ",""),
                    ("weather",                         "Rafraîchir la météo"),
                ]),
                ("CONFIGURATION", [
                    ("config token <token>",            "Token Discord selfbot"),
                    ("config city <ville,Pays>",        "Ville météo — ex: Paris,France"),
                    ("config myid <ton_id>",            "Ton ID Discord → msgs sans réponse en gras"),
                    ("config interval <secondes>",      "Fréquence refresh DMs (défaut 60)"),
                    ("config show",                     "Voir la config actuelle"),
                ]),
                ("INTERFACE", [
                    ("clear",                           "Vider la console"),
                    ("quit / exit / q",                 "Quitter mattdash"),
                    ("Flèches ←→",                      "Déplacer le curseur dans l'input"),
                    ("Home / End",                      "Début / fin de ligne"),
                ]),
                ("ASTUCES", [
                    ("● rouge",                         "Message non-répondu (en gras)"),
                    ("· gris",                          "Dernier message de toi"),
                    ("get → sidebar",                   "Membres visibles si salon de serveur"),
                    ("get → markdown",                  "**gras** *ital* -# ## spoiler etc."),
                    ("get → images",                    "Miniatures cliquables + lightbox"),
                    ("Config météo",                    "Variable — changeable sans recompiler"),
                ]),
                ("FICHIERS", [
                    (f"Config  : {CONFIG_FILE}",        ""),
                    (f"Logs    : {LOG_DIR}",            ""),
                    ("GitHub  : github.com/ton-user/mattdash", ""),
                ]),
            ]
            self.log("", self.C_DIM)
            for section_name, items in sections:
                self.log(f"── {section_name} " + "─" * (40 - len(section_name)),
                         self.C_BLUE | curses.A_BOLD)
                for cmd_str, desc in items:
                    if desc:
                        self.log(f"  {cmd_str:<38} {desc}", self.C_CYAN)
                    else:
                        self.log(f"  {cmd_str}", self.C_DIM)
                self.log("", self.C_DIM)

        else:
            self.log(f"Commande inconnue : '{cmd}'  —  tape 'help'", self.C_RED)

    # ── Gestion clavier ───────────────────────────────────────────────────────

    def handle_key(self, key):
        """Gère toutes les touches de la console."""
        if key == curses.KEY_RESIZE:
            self.scr.clear()
            return
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.input_cursor > 0:
                self.console_input = self.console_input[:self.input_cursor-1] + self.console_input[self.input_cursor:]
                self.input_cursor -= 1
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.console_input.strip():
                self.log(f"❯ {self.console_input}", self.C_DIM)
                self.exec_command(self.console_input)
            self.console_input = ""
            self.input_cursor  = 0
        elif key == curses.KEY_LEFT:
            if self.input_cursor > 0:
                self.input_cursor -= 1
        elif key == curses.KEY_RIGHT:
            if self.input_cursor < len(self.console_input):
                self.input_cursor += 1
        elif key == curses.KEY_HOME:
            self.input_cursor = 0
        elif key == curses.KEY_END:
            self.input_cursor = len(self.console_input)
        elif key == curses.KEY_DC:
            if self.input_cursor < len(self.console_input):
                self.console_input = self.console_input[:self.input_cursor] + self.console_input[self.input_cursor+1:]
        elif 32 <= key <= 126:
            self.console_input = self.console_input[:self.input_cursor] + chr(key) + self.console_input[self.input_cursor:]
            self.input_cursor += 1

    # ── Boucle principale ─────────────────────────────────────────────────────

    def run(self):
        """Boucle principale : redessine ~10 fps, lit le clavier en non-bloquant."""
        self.log("Bienvenue dans mattdash v2.0  —  tape 'help' pour l'aide complète",
                 self.C_CYAN | curses.A_BOLD)
        if not self.cfg.get("discord_token"):
            self.log("→ config token <ton_token>  pour activer Discord", self.C_YELLOW)
        if not self.cfg.get("my_discord_id"):
            self.log("→ config myid <ton_id>  pour les msgs non-répondus en gras", self.C_DIM)

        last_draw = 0
        while self.running:
            now = time.time()
            if now - last_draw >= 0.1:
                self.draw()
                last_draw = now
            try:
                key = self.scr.getch()
                if key != -1:
                    self.handle_key(key)
            except curses.error:
                pass
            time.sleep(0.02)


def main_tui():
    """Lance le TUI dans le terminal alternatif (tput smcup)."""
    curses.wrapper(lambda s: MattDash(s).run())


# ─────────────────────────────────────────────────────────────────────────────
# CLI — commandes utilisables sans lancer le TUI
# ─────────────────────────────────────────────────────────────────────────────

def cli_send(args):
    if len(args) < 2:
        print("Usage : mattdash send <channel_id> <message>")
        sys.exit(1)
    cfg   = load_config()
    cid   = args[0]
    token = cfg.get("discord_token", "")
    if not token:
        print("Erreur : token non configuré. Lance : mattdash config token <token>")
        sys.exit(1)
    fp   = None
    text = []
    for a in args[1:]:
        if a.startswith("file:"):
            fp = a[5:]
        else:
            text.append(a)
    ok, info = send_message(token, cid, " ".join(text), file_path=fp)
    print(f"✓ Message envoyé (id={info})" if ok else f"✗ {info}")
    if not ok:
        sys.exit(1)


def cli_get(args):
    if not args:
        print("Usage : mattdash get <channel_id> [nombre|all]")
        sys.exit(1)
    cfg   = load_config()
    cid   = args[0]
    count = args[1] if len(args) > 1 else "50"
    token = cfg.get("discord_token", "")
    if not token:
        print("Erreur : token non configuré.")
        sys.exit(1)
    print(f"⟳ Infos channel {cid}...")
    ch_info = get_channel_info(token, cid)
    if ch_info.get("name"):
        print(f"  → #{ch_info['name']}" + (f" ({ch_info['guild_name']})" if ch_info.get("guild_name") else ""))
    print(f"⟳ Récupération des messages ({count})...")
    msgs, err = get_channel_messages(token, cid, count)
    if err:
        print(f"✗ {err}")
        sys.exit(1)
    print(f"✓ {len(msgs)} messages.")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for candidate in [LOG_DIR, Path.home() / "Documents" / "Log"]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            outfile = candidate / f"channel_{cid}_{ts}.html"
            export_html(msgs, cid, outfile, ch_info)
            print(f"✓ {outfile}")
            return
        except PermissionError:
            continue
    print("✗ Permission refusée.")


def cli_ping(args):
    if not args:
        print("Usage : mattdash ping <host>")
        sys.exit(1)
    r = ping_host(args[0])
    print(f"● {r['host']}  min={r['min']:.1f}ms  avg={r['avg']:.1f}ms  max={r['max']:.1f}ms"
          if r["ok"] else f"✗ {r['host']} — injoignable")


def cli_config(args):
    cfg = load_config()
    if not args:
        print("Usage : mattdash config token|city|myid|interval <valeur>  |  config show")
        return
    key_map = {"token": "discord_token", "city": "weather_city",
               "myid": "my_discord_id", "interval": "dm_refresh_interval"}
    key = args[0]
    if key == "show":
        token = cfg.get("discord_token", "")
        print(f"token    = {token[:8] + '...' if len(token) > 8 else '(vide)'}")
        print(f"city     = {cfg.get('weather_city')}")
        print(f"myid     = {cfg.get('my_discord_id') or '(vide)'}")
        print(f"interval = {cfg.get('dm_refresh_interval')}s")
        print(f"fichier  = {CONFIG_FILE}")
    elif key in key_map and len(args) > 1:
        val = int(args[1]) if key == "interval" else args[1]
        cfg[key_map[key]] = val
        save_config(cfg)
        print(f"✓ {key} = {val}")
    else:
        print("Usage : mattdash config token|city|myid|interval <valeur>  |  config show")


def print_help():
    print("""mattdash v2.0 — Dashboard terminal perso

LANCER
  mattdash                           Lance le dashboard TUI interactif

DISCORD
  mattdash send <id> <message>       Envoyer un DM texte
  mattdash send <id> file:/f [msg]   Envoyer un fichier ou image
  mattdash get <id> [n|all]          Exporter un channel en HTML

RÉSEAU
  mattdash ping <host>               Ping avec latence min/avg/max

CONFIGURATION
  mattdash config token <token>      Token Discord selfbot
  mattdash config city <ville,Pays>  Ville météo (ex: Paris,France)
  mattdash config myid <id>          Ton ID Discord (msgs non-répondus en gras)
  mattdash config interval <secs>    Fréquence refresh DMs (défaut: 60)
  mattdash config show               Voir la config actuelle

FICHIERS
  Config   : ~/.config/mattdash/config.json
  Logs HTML: ~/Documents/mattdash-logs/

Dans le TUI, tape 'help' pour l'aide complète avec toutes les astuces.
""")


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    cmds = {
        "send":   lambda: cli_send(args[1:]),
        "get":    lambda: cli_get(args[1:]),
        "ping":   lambda: cli_ping(args[1:]),
        "config": lambda: cli_config(args[1:]),
    }
    if not args:
        main_tui()
    elif args[0] in cmds:
        cmds[args[0]]()
    elif args[0] in ("help", "--help", "-h"):
        print_help()
    else:
        print(f"Commande inconnue : {args[0]}")
        print_help()
        sys.exit(1)
