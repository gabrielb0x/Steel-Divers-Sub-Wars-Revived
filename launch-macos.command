#!/bin/sh
# Sub Wars Open Sourced: double-click to open the launcher in your web browser. It needs Python 3.11 or newer: the
# one of this computer (python.org, Homebrew), else a portable Python downloaded once into build/python/
# (python-build-standalone, 25 MB). If macOS refuses to open this file the first time: System Settings >
# Privacy & Security > Open Anyway (or right-click it > Open).
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3 build/python/bin/python3; do
    found=$(command -v "$py" 2>/dev/null) || continue
    [ "$found" = /usr/bin/python3 ] && continue        # Apple's: 3.9, and it asks to install the developer tools
    if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        exec "$py" subwars.py "$@"
    fi
done
case "$(uname -m)" in
    arm64) ARCH=aarch64; SUM=d66c67f16148c7454b1509c32747175f7669c8b8e105b97b92a0000d66af6e6e ;;
    *) ARCH=x86_64; SUM=73b503a2d3f47f0601265d7936744b77dc4ee75d2a3e88a470594a014dcf6822 ;;
esac
echo "Python 3.11 or newer was not found: downloading a portable Python for this project (once, 25 MB)..."
mkdir -p build && rm -rf build/python build/python.tar.gz
if curl -fL --retry 2 -o build/python.tar.gz "https://github.com/astral-sh/python-build-standalone/releases/download/20260929/cpython-3.13.15%2B20260929-$ARCH-apple-darwin-install_only_stripped.tar.gz" \
    && [ "$(shasum -a 256 build/python.tar.gz | cut -d' ' -f1)" = "$SUM" ] \
    && tar -xzf build/python.tar.gz -C build; then
    rm -f build/python.tar.gz
    exec build/python/bin/python3 subwars.py "$@"
fi
rm -rf build/python build/python.tar.gz
echo "Python 3.11 or newer is needed: https://www.python.org/downloads/"
open "https://www.python.org/downloads/"
printf "Press Enter to close. "
read -r _
