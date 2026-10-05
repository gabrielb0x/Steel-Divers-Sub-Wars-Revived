#!/bin/sh
# Sub Wars Open Sourced : ouvre le lanceur dans votre navigateur (il faut Python 3.11 ou plus récent).
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        exec "$py" subwars.py "$@"
    fi
done
echo "Il faut Python 3.11 ou plus récent (paquet python3 de votre distribution, ou https://www.python.org/downloads/)."
exit 1
