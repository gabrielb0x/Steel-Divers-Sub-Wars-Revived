#!/usr/bin/env python3
"""Sub Wars Open Sourced : le lanceur des joueurs.

    python3 subwars.py                    ouvre le lanceur dans votre navigateur
    python3 subwars.py --port 8765        sur un port fixe
    python3 subwars.py --sans-navigateur  sans ouvrir le navigateur (l'adresse s'affiche)

Il fait, avec des boutons, ce que font les outils de tools/ : préparer votre jeu, installer les mods dans
Azahar (premium, triche, caractéristiques, jeu en ligne), modifier la sauvegarde et les sous-marins, lancer
un serveur en ligne. Il ne demande que Python 3.11 ou plus récent (python.org), sans rien installer d'autre.
"""

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("Il faut Python 3.11 ou plus récent : https://www.python.org/downloads/")

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

import webui  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--port", type=int, default=0, help="port local (par défaut : un port libre)")
ap.add_argument("--sans-navigateur", action="store_true", help="ne pas ouvrir le navigateur")
args = ap.parse_args()
webui.serve(args.port, not args.sans_navigateur)
