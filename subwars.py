#!/usr/bin/env python3
"""Sub Wars Open Sourced: the players' launcher.

    python3 subwars.py                    opens the launcher in your web browser
    python3 subwars.py --port 8765        on a fixed port
    python3 subwars.py --no-browser       without opening the browser (the address is printed)

It does, with buttons, what the tools of tools/ do: prepare your game, install the mods into Azahar (premium,
cheats, characteristics, online play, music), edit the save and the submarines, run an online server. It only
needs Python 3.11 or newer (python.org), with nothing else to install.
"""

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Python 3.11 or newer is needed: https://www.python.org/downloads/")

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

import webui  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--port", type=int, default=0, help="local port (default: a free one)")
ap.add_argument("--no-browser", "--sans-navigateur", dest="no_browser", action="store_true",
                help="do not open the browser")
args = ap.parse_args()
webui.serve(args.port, not args.no_browser)
