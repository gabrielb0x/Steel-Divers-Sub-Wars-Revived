# Mods

Les mods de Steel Diver: Sub Wars pour l'émulateur **Azahar**, sous forme de **recettes** : chaque mod décrit des
changements, qui sont appliqués aux fichiers du joueur (son propre dump) au moment de la construction. Le dépôt ne
contient donc jamais de données du jeu, et un mod se partage en partageant sa recette.

## Préparer le jeu pour Azahar

Le CIA de l'eShop contient aussi le manuel électronique, resté chiffré : Azahar refuse alors toute l'installation
(« Blocked unauthorized encrypted CIA installation » dans son journal). Le jeu lui-même n'est pas chiffré :

```sh
make azahar          # ou : .venv/bin/python tools/azahar.py prepare
```

produit, à partir de `cia/*.cia` :

- `build/azahar/SteelDiverSubWars.cia` : le jeu seul, à installer (Azahar > Fichier > Installer un CIA) ;
- `build/azahar/SteelDiverSubWars.cxi` : ou à ouvrir directement (Azahar > Fichier > Charger un fichier).

## Construire et installer un mod

```sh
.venv/bin/python tools/mod.py list                       # mods disponibles
.venv/bin/python tools/mod.py build texte-titre          # -> build/mods/texte-titre/
.venv/bin/python tools/mod.py build texte-titre --install
.venv/bin/python tools/azahar.py uninstall               # revenir au jeu d'origine
```

`--install` copie le mod dans le dossier d'Azahar (`load/mods/00040000000D7E00/`, version Flatpak ou native trouvée
automatiquement, ou la variable `AZAHAR_DIR`). Un seul mod est actif à la fois. Il faut d'abord avoir lancé
`make extract` : les recettes s'appliquent aux fichiers extraits du dump.

## Écrire une recette : `mods/<nom>/mod.toml`

```toml
name = "Mon mod"
description = "Ce qu'il change"

[[text]]                                  # un texte du jeu, dans toutes les langues
key = "title_version"                     # clé <string key=...> de extracted/xml/text/*.xml
text = "Version moddée"                   # \n pour un retour à la ligne
languages = ["EU_French"]                 # facultatif

[[bxml]]                                  # n'importe quel fichier BXML, modifié comme son XML (make data)
file = "worlds/scope00_online_stage01.bxml"
select = "actor[@name='mode_settings']"   # chemin ElementTree depuis la racine
set = { timeLimit = "2400.0" }            # valeurs écrites comme dans le XML : 2400.0 est un f32, 60 un s32

[[code]]                                  # patch du code, à une adresse de code.bin (exemple de syntaxe)
address = 0x0021A82C
bytes = "8988883c"                        # ou : arm = "mov r0, #1" (assembleur keystone)
expect = "8988083d"                       # facultatif : octets attendus, protège des autres versions
```

Les adresses et les noms viennent de la décompilation (`decomp/`, `ghidra/symbols.txt`) ; les formats sont décrits
dans [../docs/formats.md](../docs/formats.md). Les modifications de scripts Pawn viendront avec un assembleur AMX.

## Mods disponibles

| Mod | Effet |
|---|---|
| `texte-titre` | exemple : « Version gratuite » devient « Version moddée » sur l'écran titre |
