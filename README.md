# Steel Diver: Sub Wars — Open Sourced

Projet de rétro-ingénierie de **Steel Diver: Sub Wars** (Nintendo / Vitei, 3DS, 2014) avec trois objectifs :

1. **Pseudo-code source** : décompiler le jeu pour comprendre comment il était codé à l'époque (`decomp/`).
2. **Portage PC** : faire tourner le même jeu, avec les mêmes graphismes, nativement sur PC (`port/`).
3. **Serveur online** : refaire un serveur pour rejouer en ligne depuis la fermeture du Nintendo Network en avril 2024 (`server/`).

> **Aucune donnée du jeu n'est versionnée** (ni CIA, ni code, ni assets, ni sortie brute du décompilateur).
> Chacun fournit son propre dump ; le `.gitignore` bloque `cia/`, `extracted/`, `decomp/raw/` et `ghidra/project/`.

## Pour les joueurs : le lanceur

*Avancement estimé : 85 % — vérifié sous Linux ; reste à l'essayer sur de vraies machines Windows et macOS.*

Il faut [Python 3.11 ou plus récent](https://www.python.org/downloads/) (rien d'autre), un émulateur
3DS de la famille de Citra — [Azahar](https://azahar-emu.org/) de préférence, ou Lime3DS, Citra, Borked3DS — et
**votre** copie du jeu européen, déchiffrée (`.cia`, `.cxi` ou `.3ds`). Windows, macOS et Linux.

1. Téléchargez ce projet (bouton *Code > Download ZIP* sur GitHub) et décompressez-le.
2. Double-cliquez sur le lanceur de votre système : `launch-windows.bat` (Windows), `launch-macos.command`
   (macOS ; la première fois, clic droit > Ouvrir), `launch-linux.sh` (Linux), ou dans un terminal
   `python3 subwars.py`. Le lanceur s'ouvre dans votre navigateur ; il ne parle qu'à votre ordinateur.
3. Onglet **Jeu** : il trouve votre jeu (dans le dossier `cia/` du projet ou dans Azahar, sinon choisissez le
   fichier) et le prépare. Avec le `.cia` déchiffré de la **mise à jour v5200** dans `cia/` (facultatif : 16
   sous-marins et 3 cartes de plus), il la prépare aussi et peut l'installer dans l'émulateur
   ([docs/update-v5200.md](docs/update-v5200.md)).
4. Onglet **Mods** : cochez **Premium** (version complète et tous les sous-marins), et si vous voulez **Toutes
   les missions**, la **Triche** (dont le tir sans délai), la **Vitesse du sous-marin** (×2 à ×15), vos
   **Caractéristiques** de sous-marins ou le **Jeu en ligne**, puis *Installer dans l'émulateur* (dans chaque
   émulateur trouvé). Toujours inclus : les **Correctifs** (sans eux, Azahar plante quand une torpille touche un
   sous-marin sous l'eau) et le **Pseudo** (votre nom en ligne et en local est le pseudo réglé dans
   l'émulateur, plus « Citra » pour tout le monde) et la **Version** (à la fin de la ligne sous le titre,
   « v0.1.34 » : la version du projet et son nombre de commits, pour savoir quelle construction on joue). Les
   mods sont construits pour la version du jeu que fait tourner l'émulateur (v0 ou v5200) ; chacun indique
   avec quelles versions il marche.
5. Onglets **Sauvegarde** (tout débloquer, médailles, drapeau premium), **Sous-marins** (caractéristiques),
   **Musique** (écouter les musiques du jeu, les remplacer par vos MP3 ou WAV, remettre celles d'origine) et
   **Serveur** (héberger des parties en ligne).

Les mêmes outils existent en ligne de commande : `tools/mod.py`, `tools/save.py`, `tools/subs.py`, `tools/music.py`
([mods/README.md](mods/README.md)). Ils fonctionnent sous Windows, macOS et Linux avec Python seul.

## État actuel

*Avancement estimé du projet : pseudo-code source 20 %, portage PC 0 %, serveur en ligne 85 %, mods 75 % (détail par section dans chaque page).*

- Extraction complète du CIA (EUR, `00040000000D7E00`, v0), déjà déchiffré : aucune clé de console n'est nécessaire.
- **Mise à jour v5200** (`0004000E000D7E00`) : extraite dans `extracted/v5200/`, installable dans Azahar ; les
  mods se construisent pour la version installée, et tous sauf le jeu en ligne marchent déjà avec elle
  ([docs/update-v5200.md](docs/update-v5200.md)).
- **Table des symboles du linker trouvée dans le RomFS** (`romfs:/map`) : 9431 fonctions avec leur vrai nom, leur
  taille et leur fichier objet d'origine (84,7 % du code). Elle est appliquée automatiquement dans Ghidra.
- 44 chemins de fichiers sources originaux retrouvés (`source/net/session.cpp`, `source/amx/amxactor.cpp`, …).
- Pseudo-code C++ exporté par fichier objet d'origine dans `decomp/raw/` (généré localement), avec les classes
  `World`, `AMXLoader` et les 647 natives Pawn typées.
- **Scripts Pawn décompilés** : les 123 scripts qui portent la logique du jeu (modes, acteurs, interface) sont
  décompilés en pseudo-Pawn lisible dans `decomp/scripts/` ([docs/pawn-scripts.md](docs/pawn-scripts.md)).

- **Données du jeu lisibles et modifiables** : le format BXML (niveaux, stats, textes) est décodé ; `make data`
  convertit les 490 fichiers en XML, et `tools/bxml.py --to-bxml` les reconvertit (identiques à l'octet près si on
  n'y touche pas). Formats documentés dans [docs/formats.md](docs/formats.md).

- **Moteur en cours de nettoyage** (`decomp/src/`) : boucle principale, chargeur de scripts, monde (pool d'acteurs,
  format des niveaux, replays), système, cycle de vie des acteurs.
- **Mods pour Azahar** : `make azahar` rend le jeu installable dans l'émulateur (le CIA de l'eShop est refusé à cause
  du manuel chiffré), et `tools/mod.py` construit et installe des mods décrits par des recettes
  ([mods/README.md](mods/README.md), [docs/mods.md](docs/mods.md)).
- **Le jeu en ligne refonctionne** : serveur maison ([server/](server/README.md), Python sans dépendance) et mod
  `online` pour Azahar. Deux émulateurs se connectent, se trouvent par le matchmaking et jouent une bataille
  ensemble. Entre deux maisons, le serveur ouvre lui-même ses ports sur la box (UPnP) et le lanceur donne
  l'adresse à partager. Protocole reconstitué : [docs/online.md](docs/online.md).

```sh
cd server && python3 -m sdsw_server                        # le serveur (royaumes « emulateur » et « pc »)
.venv/bin/python tools/mod.py build online --set server=<adresse> --install    # chaque joueur
.venv/bin/python tools/mod.py build online triche --set server=<adresse> --install   # avec la triche
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
- **Autres mods** : `missions` (les 21 missions jouables tout de suite, sans toucher à la sauvegarde), `vitesse`
  (votre sous-marin ×2, ×3, ×5, ×10 ou ×15), `triche` (invincible, torpilles infinies et tir sans délai…).

```sh
.venv/bin/python tools/mod.py build premium --install       # version complète et tous les sous-marins
.venv/bin/python tools/save.py show                         # la sauvegarde ; unlock all, set, export…
```

Détails : [docs/initial-analysis.md](docs/initial-analysis.md) · Plan : [docs/roadmap.md](docs/roadmap.md) · IA
aussi forte qu'un joueur, combien de parties : [docs/ai.md](docs/ai.md)

## Arborescence

*Avancement estimé : 100 % — à jour.*

```
cia/               ton dump .cia (ignoré par git)
extracted/         sortie de l'extraction : code.bin, nsub.elf, exefs/, romfs/ ; v5200/ : la mise à jour (ignoré)
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

*Avancement estimé : 90 % — la chaîne de rétro-ingénierie (Ghidra) n'est décrite et vérifiée que sous Linux.*

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

*Avancement estimé : 100 %.*

Le code de ce dépôt (outils, scripts, portage, serveur, documentation) est sous licence [MIT](LICENSE).
Elle ne couvre pas le jeu : Steel Diver: Sub Wars, ses données et son code restent la propriété de Nintendo.
