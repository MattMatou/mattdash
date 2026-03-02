# mattdash

Dashboard terminal perso pour Debian/Linux.

```
─────────────────── SYSTÈME  14:32:07 ───────────────────
⏱ Uptime: 2h 14m                    🌐 IP: 192.168.1.42
🔲 CPU:   ██████░░░░░░░░░░░░░░ 28.4%
💾 RAM:   ████████████░░░░░░░░ 3200M/8000M (40%)
🗄 Disque: ████░░░░░░░░░░░░░░░░ 42G/500G (8%)
📊 Load:  1m:0.45  5m:0.31  15m:0.28
─────────────── MÉTÉO & DMs DISCORD ─────────────────────
🌤 Paris: ⛅ +12°C
Derniers messages :
● @Alice  [2024-01-15]  Alice: t'as vu le truc de tout à...   ← non-répondu (gras)
· @Bob    [2024-01-14]  toi: ouais c'est dingue
═══════════════════ CONSOLE ══════════════════════════════
❯ _
```

## Ce que ça fait

- **Stats système live** — CPU, RAM, disque, load, IP locale (refresh 1s)
- **Météo** — via wttr.in, ville configurable, pas hardcodée
- **15 derniers DMs Discord** — les non-répondus en gras avec ● rouge
- **Envoi de messages et fichiers** — images, vidéos, PDFs, n'importe quoi
- **Export HTML de channels** — avec markdown Discord complet, images inline, sidebar membres si salon de serveur
- **Ping latence** — min/avg/max en ms

## Installation

### Depuis le .deb (recommandé sur Debian/Ubuntu)

```bash
# Télécharge la dernière release
wget https://github.com/TON_USER/mattdash/releases/latest/download/mattdash_latest_all.deb

# Installe les dépendances + le paquet
sudo apt install python3-psutil iputils-ping -y
sudo dpkg -i mattdash_latest_all.deb
```

### Depuis les sources

```bash
git clone https://github.com/TON_USER/mattdash.git
cd mattdash
chmod +x install.sh
./install.sh
```

### Manuel (sans droits root)

```bash
git clone https://github.com/TON_USER/mattdash.git
cd mattdash
cp mattdash.py ~/.local/bin/mattdash
chmod +x ~/.local/bin/mattdash
```

## Configuration

```bash
# Token Discord selfbot (obligatoire pour les fonctions Discord)
mattdash config token TON_TOKEN_ICI

# Ville météo (variable — pas dans le code)
mattdash config city Paris,France

# Ton ID Discord (pour détecter les messages sans réponse)
# Trouve-le dans Discord > Paramètres > Avancé > Mode développeur
# puis clic droit sur ton profil > Copier l'identifiant
mattdash config myid 123456789012345678

# Voir la config actuelle
mattdash config show
```

La config est stockée dans `~/.config/mattdash/config.json`.

## Commandes

### Dans le TUI (dashboard interactif)

| Commande | Description |
|---|---|
| `send <id> <message>` | Envoyer un message texte (espaces OK) |
| `send <id> file:/chemin [légende]` | Envoyer une image ou un fichier |
| `get <id> <n\|all>` | Exporter un channel en HTML |
| `dms` | Rafraîchir les 15 derniers DMs |
| `ping <host>` | Latence vers un hôte ou IP |
| `weather` | Rafraîchir la météo |
| `config token <token>` | Changer le token Discord |
| `config city <ville,Pays>` | Changer la ville météo |
| `config myid <id>` | Définir ton ID Discord |
| `config show` | Voir la config |
| `clear` | Vider la console |
| `help` | Aide complète |
| `quit` / `q` | Quitter |

### En ligne de commande (sans TUI)

```bash
mattdash                              # Lance le dashboard
mattdash send 123456789 salut !       # Envoyer un message
mattdash send 123456789 file:~/photo.png regarde  # Envoyer une image
mattdash get 123456789 all            # Exporter tout un channel en HTML
mattdash get 123456789 100            # Exporter les 100 derniers messages
mattdash ping 8.8.8.8                 # Ping Google DNS
mattdash ping github.com            # Ping un domaine
mattdash config show                  # Voir la config
mattdash help                         # Aide
```

## Export HTML

Les exports sont sauvegardés dans `~/Documents/mattdash-logs/` (ou `~/Documents/Log/` en fallback).

Chaque fichier inclut :
- Formatage markdown Discord complet (`**gras**`, `*ital*`, `-#`, `##`, `||spoiler||`, etc.)
- Images en miniatures cliquables avec lightbox
- Vidéos avec lecteur intégré
- Fichiers avec lien de téléchargement
- Stickers Discord, emojis custom
- Embeds avec couleur et image
- Messages cités (réponses) avec lien vers le message d'origine
- Réactions emoji avec compteur
- **Sidebar avec les membres** si c'est un salon de serveur
- Barre de recherche en temps réel
- Spoilers révélables au clic
- Thème dark (Catppuccin-inspired)

## Fichiers

```
~/.config/mattdash/config.json   Config (token, ville, etc.)
~/Documents/mattdash-logs/      Exports HTML
/usr/lib/mattdash/mattdash.py  Code principal
/usr/bin/mattdash                Launcher
```

## Dépendances

- Python 3.9+
- `python3-psutil` (stats système plus précises — optionnel, fallback sur /proc)
- `iputils-ping` (commande ping)
- Connexion internet (météo, Discord API)

## Sécurité

Le token Discord est stocké localement dans `~/.config/mattdash/config.json`.
Ce dépôt ne contient **aucun token**. Ne commit jamais ton fichier de config.

Le `.gitignore` exclut automatiquement les fichiers de config et les exports HTML.

## Licence

MIT — fait par Matt pour un usage perso, partage libre.
