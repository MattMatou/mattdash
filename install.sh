#!/bin/bash
# install.sh — Installation de mattdash depuis les sources
# Usage : chmod +x install.sh && ./install.sh
set -e

echo "=== mattdash installer ==="

# Vérifie qu'on est pas root (on a pas besoin sauf pour /usr/bin)
if [ "$EUID" -eq 0 ]; then
    echo "⚠ Lance ce script en tant qu'utilisateur normal, pas root."
    echo "  Les permissions sudo seront demandées si besoin."
fi

# Vérifie Python 3.9+
if ! python3 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
    echo "✗ Python 3.9+ requis."
    exit 1
fi
echo "✓ Python $(python3 --version)"

# Installe les dépendances si apt est dispo
if command -v apt &>/dev/null; then
    echo "→ Installation des dépendances apt..."
    sudo apt install -y python3-psutil iputils-ping 2>/dev/null || true
fi

# Crée le dossier lib
sudo mkdir -p /usr/lib/mattdash

# Copie le script principal
sudo cp mattdash.py /usr/lib/mattdash/mattdash.py
sudo chmod 644 /usr/lib/mattdash/mattdash.py

# Crée le launcher dans /usr/bin
sudo tee /usr/bin/mattdash > /dev/null << 'LAUNCHER'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/usr/lib/mattdash')
from mattdash import *
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
LAUNCHER

sudo chmod 755 /usr/bin/mattdash

# Crée les dossiers de log
mkdir -p ~/Documents/Log

echo ""
echo "✓ mattdash installé !"
echo ""
echo "Prochaines étapes :"
echo "  mattdash config token TON_TOKEN_DISCORD"
echo "  mattdash config city Paris,France"
echo "  mattdash config myid TON_ID_DISCORD"
echo "  mattdash"
