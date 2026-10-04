# Steel Diver: Sub Wars — Open Sourced

Projet de rétro-ingénierie de **Steel Diver: Sub Wars** (Nintendo / Vitei, 3DS, 2014) avec trois objectifs :

1. **Pseudo-code source** : décompiler le jeu pour comprendre comment il était codé à l'époque (`decomp/`).
2. **Portage PC** : faire tourner le même jeu, avec les mêmes graphismes, nativement sur PC (`port/`).
3. **Serveur online** : refaire un serveur pour rejouer en ligne depuis la fermeture du Nintendo Network en avril 2024 (`server/`).

> **Aucune donnée du jeu n'est versionnée** (ni CIA, ni code, ni assets, ni sortie brute du décompilateur).
> Chacun fournit son propre dump ; le `.gitignore` bloque `cia/`, `extracted/`, `decomp/raw/` et `ghidra/project/`.

## État actuel

- Extraction complète du CIA (EUR, `00040000000D7E00`, v0), déjà déchiffré : aucune clé de console n'est nécessaire.
- **Table des symboles du linker trouvée dans le RomFS** (`romfs:/map`) : 9431 fonctions avec leur vrai nom, leur
  taille et leur fichier objet d'origine (84,7 % du code). Elle est appliquée automatiquement dans Ghidra.
- 44 chemins de fichiers sources originaux retrouvés (`source/net/session.cpp`, `source/amx/amxactor.cpp`, …).
- Pseudo-code C++ exporté par fichier objet d'origine dans `decomp/raw/` (généré localement), avec les classes
  `World`, `AMXLoader` et les 647 natives Pawn typées.
- **Scripts Pawn décompilés** : les 123 scripts qui portent la logique du jeu (modes, acteurs, interface) sont
  décompilés en pseudo-Pawn lisible dans `decomp/scripts/` ([docs/scripts-pawn.md](docs/scripts-pawn.md)).

- **Données du jeu lisibles** : le format BXML (niveaux, stats, textes) est décodé ; `make data` convertit les 490
  fichiers en XML. Formats documentés dans [docs/formats.md](docs/formats.md).

Détails : [docs/analyse-initiale.md](docs/analyse-initiale.md) · Plan : [docs/roadmap.md](docs/roadmap.md)

## Arborescence

```
cia/               ton dump .cia (ignoré par git)
extracted/         sortie de l'extraction : code.bin, nsub.elf, exefs/, romfs/ (ignoré)
tools/             scripts Python : extraction CIA, code.bin -> ELF, désassembleur/décompilateur Pawn (amx*.py)
ghidra/scripts/    scripts Ghidra : symboles du map, SVC, pointeurs de code, export du pseudo-code
ghidra/symbols.txt noms et prototypes ajoutés à la main (versionnés, réappliqués à chaque analyse/export)
ghidra/types.h     types C reconstitués (idem)
ghidra/project/    base Ghidra, jetable : `make analyze` la recrée (ignorée)
decomp/            pseudo-code source : raw/ (C++ Ghidra), scripts/ (Pawn décompilé), src/ (nettoyé à la main)
port/              portage PC
server/            serveur online
docs/              notes de rétro-ingénierie
```

## Installation

Prérequis : Linux, Python 3.10+, Java 21+, [Ghidra 12](https://github.com/NationalSecurityAgency/ghidra/releases)
extrait dans un chemin **sans accents** (par ex. `~/tools/`, le chargement de Ghidra échoue sinon).

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
