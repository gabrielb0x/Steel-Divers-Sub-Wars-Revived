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

- `build/azahar/SteelDiverSubWars_original.cia` : le jeu seul, à installer (Azahar > Fichier > Installer un CIA) ;
- `build/azahar/SteelDiverSubWars_original.cxi` : ou à ouvrir directement (Azahar > Fichier > Charger un fichier).

`tools/mod.py build <mod> --cxi` y ajoute `SteelDiverSubWars_<mod>[_<serveur>].cxi`, le jeu avec le patch de code
du mod déjà appliqué, pour garder la version d'origine et la version moddée côte à côte. `build/azahar/LISEZMOI.txt`
dit à quoi sert chaque fichier. Ce sont des copies du jeu : elles ne se partagent pas.

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
bytes = "8988883c"                        # ou : arm = "mov r0, #1" (assembleur keystone),
                                          # ascii = "texte", utf16 = "texte", words = ["0x1234"]
expect = "8988083d"                       # facultatif : octets attendus, protège des autres versions
max_size = 116                            # facultatif : taille maximale (la fin de la fonction remplacée)

[params.server]                           # facultatif : valeur donnée à la construction
help = "adresse du serveur"               #   tools/mod.py build <nom> --set server=1.2.3.4
default = "127.0.0.1"                     # et utilisée dans les [[code]] sous la forme ${server}

[identity]                                # facultatif : identité de joueur pour un serveur en ligne
scope = "${server}:${port}"               # donne ${pid}, ${password} et ${token}
```

Une identité est créée une fois par serveur et gardée dans `~/.config/sub-wars-open-sourced/identites.json` :
reconstruire le mod garde le même compte.

Les adresses et les noms viennent de la décompilation (`decomp/`, `ghidra/symbols.txt`) ; les formats sont décrits
dans [../docs/formats.md](../docs/formats.md). Les modifications de scripts Pawn viendront avec un assembleur AMX.

## Mods disponibles

| Mod | Effet |
|---|---|
| `en-ligne` | jeu en ligne sur un serveur [Sub Wars Open Sourced](../server/README.md) |
| `texte-titre` | exemple : « Version gratuite » devient « Version moddée » sur l'écran titre |

## Jouer en ligne

```sh
make extract                                               # une fois : les fichiers du dump
.venv/bin/python tools/mod.py build en-ligne --set server=192.0.2.10 --install
```

`server` est l'adresse du serveur (IP ou nom, 31 caractères au plus ; `127.0.0.1` par défaut, pour un serveur sur
la même machine) et `port` son port d'authentification (61000 par défaut, le royaume des joueurs sur émulateur).
Ensuite, dans le jeu : *Multiplayer > Internet Battle*. Le jeu n'a pas besoin d'être modifié : Azahar applique le
patch (`exefs/code.ips`) au lancement.

Pourquoi un patch est nécessaire et ce qu'il change : [../docs/online.md](../docs/online.md).
