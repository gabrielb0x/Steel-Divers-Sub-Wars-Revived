#!/bin/sh
# Sub Wars Open Sourced: installs the project into a folder Sub-Wars-Open-Sourced next to this file, then opens
# the launcher, which sets the game up. Put this file where you want that folder, then:
#   Linux   sh install-here.sh   (or allow it to run as a program, and double-click it)
#   macOS   double-click "Install here.command" (from Install-here-macOS.zip; the first time macOS may ask you to
#           allow it: System Settings > Privacy & Security > Open Anyway)
# Already installed: it opens the launcher, which updates itself.
cd "$(dirname "$0")" || exit 1
URL="https://github.com/gabrielb0x/Sub-Wars-Steel-Divers-Open-Sourced/releases/latest/download/Sub-Wars-Open-Sourced.zip"
ZIP="Sub-Wars-Open-Sourced.zip"

fail() {
    rm -f "$ZIP"
    echo "$1"
    printf "Press Enter to close. "
    read -r _
    exit 1
}

if [ -f Sub-Wars-Open-Sourced/subwars.py ]; then
    echo "Sub Wars Open Sourced is already here: opening the launcher (it updates itself)."
else
    echo "Downloading Sub Wars Open Sourced..."
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 2 -o "$ZIP" "$URL" || fail "The download failed: check the Internet connection, then try again."
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$ZIP" "$URL" || fail "The download failed: check the Internet connection, then try again."
    else
        fail "curl or wget is needed to download the project."
    fi
    echo "Unpacking..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$ZIP" || fail "The unpacking failed."
    elif command -v bsdtar >/dev/null 2>&1; then
        bsdtar -xf "$ZIP" || fail "The unpacking failed."
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m zipfile -e "$ZIP" . || fail "The unpacking failed."
    else
        fail "unzip is needed to unpack the project."
    fi
    rm -f "$ZIP"
    [ -f Sub-Wars-Open-Sourced/subwars.py ] || fail "The download did not hold the project: try again later."
fi
case "$(uname -s)" in
    Darwin) exec sh Sub-Wars-Open-Sourced/launch-macos.command --setup ;;
    *) exec sh Sub-Wars-Open-Sourced/launch-linux.sh --setup ;;
esac
