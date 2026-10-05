#!/bin/sh
# Sub Wars Open Sourced : double-cliquez pour ouvrir le lanceur dans votre navigateur.
# Il faut Python 3.11 ou plus récent (python.org), rien d'autre. Si macOS refuse de l'ouvrir la première
# fois : clic droit sur ce fichier > Ouvrir.
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        exec "$py" subwars.py "$@"
    fi
done
echo "Il faut Python 3.11 ou plus récent : https://www.python.org/downloads/"
open "https://www.python.org/downloads/"
printf "Appuyez sur Entrée pour fermer. "
read -r _
