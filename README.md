# Steel Diver: Sub Wars — Open Sourced

Projet de rétro-ingénierie de **Steel Diver: Sub Wars** (Nintendo / Vitei, 3DS, 2014) avec trois objectifs :

1. **Pseudo-code source** : décompiler le jeu pour comprendre comment il était codé à l'époque (`decomp/`).
2. **Portage PC** : faire tourner le même jeu, avec les mêmes graphismes, nativement sur PC (`port/`).
3. **Serveur online** : refaire un serveur pour rejouer en ligne depuis la fermeture du Nintendo Network en avril 2024 (`server/`).

> **Aucune donnée du jeu n'est versionnée** (ni CIA, ni code, ni assets, ni sortie brute du décompilateur).
> Chacun fournit son propre dump ; le `.gitignore` bloque `cia/`, `extracted/`, `decomp/raw/` et `ghidra/project/`.

## Pour les joueurs : le lanceur

Il faut [Python 3.11 ou plus récent](https://www.python.org/downloads/) (rien d'autre), un émulateur
3DS de la famille de Citra — [Azahar](https://azahar-emu.org/) de préférence, ou Lime3DS, Citra, Borked3DS — et
**votre** copie du jeu européen, déchiffrée (`.cia`, `.cxi` ou `.3ds`). Windows, macOS et Linux.

1. Téléchargez ce projet (bouton *Code > Download ZIP* sur GitHub) et décompressez-le.
2. Double-cliquez sur le lanceur de votre système : `lancer-windows.bat` (Windows), `lancer-macos.command`
   (macOS ; la première fois, clic droit > Ouvrir), `lancer-linux.sh` (Linux), ou dans un terminal
   `python3 subwars.py`. Le lanceur s'ouvre dans votre navigateur ; il ne parle qu'à votre ordinateur.
3. Onglet **Jeu** : il trouve votre jeu (dans le dossier `cia/` du projet ou dans Azahar, sinon choisissez le
   fichier) et le prépare.
4. Onglet **Mods** : cochez **Premium** (version complète et les 23 sous-marins), et si vous voulez **Toutes
   les missions**, la **Triche** (dont le tir sans délai), la **Vitesse du sous-marin** (×2 à ×15), vos
   **Caractéristiques** de sous-marins ou le **Jeu en ligne**, puis *Installer dans l'émulateur* (dans chaque
   émulateur trouvé). Toujours inclus : les **Correctifs** (sans eux, Azahar plante quand une torpille touche un
   sous-marin sous l'eau) et le **Pseudo** (votre nom en ligne et en local est le pseudo réglé dans
   l'émulateur, plus « Citra » pour tout le monde).
5. Onglets **Sauvegarde** (tout débloquer, médailles, drapeau premium), **Sous-marins** (caractéristiques) et
   **Serveur** (héberger des parties en ligne).

Les mêmes outils existent en ligne de commande : `tools/mod.py`, `tools/save.py`, `tools/subs.py`
([mods/README.md](mods/README.md)). Ils fonctionnent sous Windows, macOS et Linux avec Python seul.

## État actuel

- Extraction complète du CIA (EUR, `00040000000D7E00`, v0), déjà déchiffré : aucune clé de console n'est nécessaire.
- **Table des symboles du linker trouvée dans le RomFS** (`romfs:/map`) : 9431 fonctions avec leur vrai nom, leur
  taille et leur fichier objet d'origine (84,7 % du code). Elle est appliquée automatiquement dans Ghidra.
- 44 chemins de fichiers sources originaux retrouvés (`source/net/session.cpp`, `source/amx/amxactor.cpp`, …).
- Pseudo-code C++ exporté par fichier objet d'origine dans `decomp/raw/` (généré localement), avec les classes
  `World`, `AMXLoader` et les 647 natives Pawn typées.
- **Scripts Pawn décompilés** : les 123 scripts qui portent la logique du jeu (modes, acteurs, interface) sont
  décompilés en pseudo-Pawn lisible dans `decomp/scripts/` ([docs/scripts-pawn.md](docs/scripts-pawn.md)).

- **Données du jeu lisibles et modifiables** : le format BXML (niveaux, stats, textes) est décodé ; `make data`
  convertit les 490 fichiers en XML, et `tools/bxml.py --to-bxml` les reconvertit (identiques à l'octet près si on
  n'y touche pas). Formats documentés dans [docs/formats.md](docs/formats.md).

- **Moteur en cours de nettoyage** (`decomp/src/`) : boucle principale, chargeur de scripts, monde (pool d'acteurs,
  format des niveaux, replays), système, cycle de vie des acteurs.
- **Mods pour Azahar** : `make azahar` rend le jeu installable dans l'émulateur (le CIA de l'eShop est refusé à cause
  du manuel chiffré), et `tools/mod.py` construit et installe des mods décrits par des recettes
  ([mods/README.md](mods/README.md), [docs/mods.md](docs/mods.md)).
- **Le jeu en ligne refonctionne** : serveur maison ([server/](server/README.md), Python sans dépendance) et mod
  `en-ligne` pour Azahar. Deux émulateurs se connectent, se trouvent par le matchmaking et jouent une bataille
  ensemble. Entre deux maisons, le serveur ouvre lui-même ses ports sur la box (UPnP) et le lanceur donne
  l'adresse à partager. Protocole reconstitué : [docs/online.md](docs/online.md).

```sh
cd server && python3 -m sdsw_server                        # le serveur (royaumes « emulateur » et « pc »)
.venv/bin/python tools/mod.py build en-ligne --set server=<adresse> --install    # chaque joueur
.venv/bin/python tools/mod.py build en-ligne triche --set server=<adresse> --install   # avec la triche
```

  Le serveur règle le nombre de joueurs humains par partie et décide quoi faire des tricheurs. Un joueur
  resté seul une minute joue contre des bots qui rejoignent la partie comme des joueurs (noms, vrais
  sous-marins, niveaux) ; équipes (4v4, 1v4…), carte, niveau, durée et noms se règlent dans le lanceur
  ([server/README.md](server/README.md)).
- **Premium sans l'eShop** : le mod `premium` débloque la version complète, les 23 sous-marins (dont les 5
  historiques vendus à part), les motifs et l'équipage ([docs/premium.md](docs/premium.md)).
- **Éditeur de sauvegarde** : `tools/save.py` affiche et modifie la sauvegarde d'Azahar (déblocages, médailles,
  n'importe quelle valeur, export JSON) ; format dans [docs/formats.md](docs/formats.md#sauvegarde).
- **Plantage d'Azahar corrigé** : quand une torpille touchait un sous-marin sous l'eau, l'émulateur remplissait
  la mémoire et se faisait tuer par le système. C'est un bug du JIT de shaders d'Azahar (et de Citra), déclenché
  par le geometry shader de la nappe d'huile ; le mod `correctifs`, inclus dans tous les mods, le contourne
  ([docs/mods.md](docs/mods.md#correctifs)).
- **60 images par seconde** : le mod `60fps` dessine une image intermédiaire entre deux pas de simulation (acteurs
  et caméra à mi-chemin) ; la partie elle-même reste à 30 pas par seconde, donc identique et compatible en ligne
  avec des joueurs à 30. Dans Azahar, si le jeu reste à 30 dans les scènes chargées, monter Émulation >
  Configurer > Débogage > Vitesse d'horloge du CPU à 200 %. 120 images/s : impossible dans un émulateur (l'écran
  émulé est à 60 Hz), prévu dans le portage PC ([docs/mods.md](docs/mods.md#60-et-120-images-par-seconde)).
- **Autres mods** : `missions` (les 21 missions jouables tout de suite, sans toucher à la sauvegarde), `vitesse`
  (votre sous-marin ×2, ×3, ×5, ×10 ou ×15), `triche` (invincible, torpilles infinies et tir sans délai…).

```sh
.venv/bin/python tools/mod.py build premium --install       # version complète et tous les sous-marins
.venv/bin/python tools/save.py show                         # la sauvegarde ; unlock all, set, export…
```

Détails : [docs/analyse-initiale.md](docs/analyse-initiale.md) · Plan : [docs/roadmap.md](docs/roadmap.md)

## Arborescence

```
cia/               ton dump .cia (ignoré par git)
extracted/         sortie de l'extraction : code.bin, nsub.elf, exefs/, romfs/ (ignoré)
tools/             scripts Python : extraction CIA, code.bin -> ELF, Pawn (amx*.py), BXML, Azahar, mods
mods/              recettes de mods (aucune donnée du jeu : elles s'appliquent au dump du joueur)
ghidra/scripts/    scripts Ghidra : symboles du map, SVC, pointeurs de code, export du pseudo-code
ghidra/symbols.txt noms et prototypes ajoutés à la main (versionnés, réappliqués à chaque analyse/export)
ghidra/types.h     types C reconstitués (idem)
ghidra/project/    base Ghidra, jetable : `make analyze` la recrée (ignorée)
decomp/            pseudo-code source : raw/ (C++ Ghidra), scripts/ (Pawn décompilé), src/ (nettoyé à la main)
port/              portage PC
server/            serveur online (royaumes émulateur et PC, détection de NAT, tests)
docs/              notes de rétro-ingénierie
```

## Installation

Pour jouer, Python 3.11 suffit (voir plus haut). Pour la rétro-ingénierie : Linux, Python 3.11+, Java 21+,
[Ghidra 12](https://github.com/NationalSecurityAgency/ghidra/releases) extrait dans un chemin **sans accents**
(par ex. `~/tools/`, le chargement de Ghidra échoue sinon).

```sh
./setup.sh          # venv Python + détection de Ghidra (écrit local.env)
cp <ton dump>.cia cia/
make                # extraction -> ELF -> analyse Ghidra -> pseudo-code C++ -> scripts Pawn décompilés
```

Étapes individuelles : `make extract`, `make elf`, `make analyze`, `make export`, `make scripts`, `make data`.
Pour explorer dans l'interface : lancer Ghidra et ouvrir `ghidra/project/SteelDiver.gpr`.

## Licence

Le code de ce dépôt (outils, scripts, portage, serveur, documentation) est sous licence [MIT](LICENSE).
Elle ne couvre pas le jeu : Steel Diver: Sub Wars, ses données et son code restent la propriété de Nintendo.
