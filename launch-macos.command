#!/bin/sh
# Sub Wars Open Sourced: double-click to open the launcher in your web browser.
# It needs Python 3.11 or newer (python.org), nothing else. If macOS refuses to open it the first time:
# right-click this file > Open.
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        exec "$py" subwars.py "$@"
    fi
done
echo "Python 3.11 or newer is needed: https://www.python.org/downloads/"
open "https://www.python.org/downloads/"
printf "Press Enter to close. "
read -r _
