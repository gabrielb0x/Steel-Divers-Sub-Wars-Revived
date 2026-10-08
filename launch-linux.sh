#!/bin/sh
# Sub Wars Open Sourced: opens the launcher in your web browser. It needs Python 3.11 or newer: the one of this
# computer, else a portable Python downloaded once into build/python/ (python-build-standalone, 30 MB).
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.13 python3.12 python3.11 python3 build/python/bin/python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        exec "$py" subwars.py "$@"
    fi
done
case "$(uname -m)" in
    x86_64|amd64) ARCH=x86_64; SUM=c552deaf9ed0e678dee4ccc760d6dcd7cab33f1bd43e8037123b4a4db8508e14 ;;
    aarch64|arm64) ARCH=aarch64; SUM=3807936bef22d3e347454df4f8774c786f98c7caa5e7328425e7b40766a9cff8 ;;
    *) ARCH= ;;
esac
if [ -n "$ARCH" ] && command -v curl >/dev/null 2>&1; then
    echo "Python 3.11 or newer was not found: downloading a portable Python for this project (once, 30 MB)..."
    mkdir -p build && rm -rf build/python build/python.tar.gz
    if curl -fL --retry 2 -o build/python.tar.gz "https://github.com/astral-sh/python-build-standalone/releases/download/20260929/cpython-3.13.15%2B20260929-$ARCH-unknown-linux-gnu-install_only_stripped.tar.gz" \
        && [ "$(sha256sum build/python.tar.gz | cut -d' ' -f1)" = "$SUM" ] \
        && tar -xzf build/python.tar.gz -C build; then
        rm -f build/python.tar.gz
        exec build/python/bin/python3 subwars.py "$@"
    fi
    rm -rf build/python build/python.tar.gz
fi
echo "Python 3.11 or newer is needed (the python3 package of your distribution, or https://www.python.org/downloads/)."
exit 1
