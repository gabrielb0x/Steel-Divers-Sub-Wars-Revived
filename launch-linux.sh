#!/bin/sh
# Sub Wars Open Sourced: opens the launcher in your web browser (it needs Python 3.11 or newer).
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        exec "$py" subwars.py "$@"
    fi
done
echo "Python 3.11 or newer is needed (the python3 package of your distribution, or https://www.python.org/downloads/)."
exit 1
