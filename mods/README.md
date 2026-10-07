# Mods

> Le plus simple : le lanceur `subwars.py` (à la racine du projet) fait tout ce qui suit avec des boutons, dans
> le navigateur. Cette page décrit les outils en ligne de commande et le format des recettes. Ils n'ont besoin que
> de Python 3.11 (pas de venv) : `python3 tools/mod.py …` marche aussi bien que `.venv/bin/python tools/mod.py …`.

Les mods de Steel Diver: Sub Wars pour l'émulateur **Azahar**, sous forme de **recettes** : chaque mod décrit des
changements, qui sont appliqués aux fichiers du joueur (son propre dump) au moment de la construction. Le dépôt ne
contient donc jamais de données du jeu, et un mod se partage en partageant sa recette.

## Préparer le jeu pour Azahar

*Avancement estimé : 100 %.*

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

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/mod.py list                       # mods disponibles
.venv/bin/python tools/mod.py build texte-titre          # -> build/mods/texte-titre/
.venv/bin/python tools/mod.py build texte-titre --install
.venv/bin/python tools/azahar.py uninstall               # revenir au jeu d'origine
```

`--install` copie le mod dans le dossier d'Azahar (`load/mods/00040000000D7E00/`, version Flatpak ou native trouvée
automatiquement, ou la variable `AZAHAR_DIR`). Un seul mod est actif à la fois. Il faut d'abord avoir lancé
`make extract` : les recettes s'appliquent aux fichiers extraits du dump.

Le mod est construit pour la version du jeu que fait tourner l'émulateur : la v0, ou la **mise à jour v5200** si
elle y est installée ([../docs/mise-a-jour.md](../docs/mise-a-jour.md)). `--version v0` ou `--version v5200` en
choisit une ; `tools/mod.py list` dit avec quelles versions marche chaque mod. Une construction pour la v5200 va
dans `build/mods/<nom>-v5200/`.

```sh
.venv/bin/python tools/azahar.py install-update            # la mise à jour (son CIA déchiffré dans cia/) dans Azahar
.venv/bin/python tools/azahar.py where                     # la version du jeu dans chaque émulateur, les mods installés
.venv/bin/python tools/azahar.py uninstall-update          # revenir à la v0
```

Chaque construction inclut les **correctifs** du jeu (`mods/correctifs`, `always = true`), sauf avec `--no-fixes` ;
`tools/mod.py build correctifs --install` les installe seuls.

## Écrire une recette : `mods/<nom>/mod.toml`

*Avancement estimé : 100 %.*

```toml
name = "Mon mod"
description = "Ce qu'il change"

[[text]]                                  # un texte du jeu, dans toutes les langues
key = "title_version"                     # clé <string key=...> de extracted/xml/text/*.xml
text = "Version moddée"                   # \n pour un retour à la ligne, ${option} pour une valeur donnée
                                          # à la construction ; un caractère absent de la police est signalé
languages = ["EU_French"]                 # facultatif
# like = "internet_mode_warning"          # facultatif : une clé que le jeu n'a pas, créée sur le modèle de
                                          # celle-ci (police, interligne)
# ou append = "\nligne de plus"           # au lieu de text : ajouté à la fin, après tous les text = de la
                                          # construction (plusieurs mods sur la même ligne)

[[bxml]]                                  # n'importe quel fichier BXML, modifié comme son XML (make data)
file = "worlds/scope00_online_stage01.bxml"
select = "actor[@name='mode_settings']"   # chemin ElementTree depuis la racine
set = { timeLimit = "2400.0" }            # valeurs écrites comme dans le XML : 2400.0 est un f32, 60 un s32
# rename = { ancien = "nouveau" }         # renomme des attributs sans changer leur place (avant set)
# remove = true                           # ou : supprime les nœuds choisis

[[amx]]                                   # un script Pawn ; adresses de decomp/scripts/asm/<script>.asm
file = "amx/periscope_move.amx"
at = 0x5D4C                               # une chaîne du segment de données (sans « at » : toutes)
string = "player.muteki"
replace = "mode.ready"                    # pas plus longue que l'originale
# ou un opérande d'instruction : address = 0x130D0, operand = 0, value = 1, expect = 0
# (les sauts sont relatifs à l'instruction : value = 8 saute à l'instruction suivante)
# ou du code Pawn ajouté au script : asm_file = "fichier.pasm" (dans le dossier du mod) ou asm = "..."

[[shader]]                                # une instruction d'un shader PICA200 (shaders/*.shbin)
file = "shaders/metaball.shbin"
instruction = 0x084                       # son numéro dans le code, comme l'affiche tools/shbin.py
expect = 0xA4021800                       # facultatif : l'instruction d'origine
value = 0x84000000                        # nop

[[code]]                                  # patch du code, à une adresse de code.bin (exemple de syntaxe)
address = 0x0021A82C
bytes = "8988883c"                        # ou : arm = "mov r0, #1" (assembleur tools/armasm.py),
                                          # ascii = "texte", utf16 = "texte", words = ["0x1234"]
                                          # (les étiquettes d'un bloc arm : ${arm_<étiquette>} ensuite)
expect = "8988083d"                       # facultatif : octets attendus, protège des autres versions
max_size = 116                            # facultatif : taille maximale (la fin de la fonction remplacée)

[params.server]                           # facultatif : valeur donnée à la construction
help = "adresse du serveur"               #   tools/mod.py build <nom> --set server=1.2.3.4
default = "127.0.0.1"                     # et utilisée dans les [[code]] sous la forme ${server}
# choices = ["2", "3", "5"]               # ou : les seules valeurs acceptées (liste dans le lanceur)

[identity]                                # facultatif : identité de joueur pour un serveur en ligne
scope = "${server}:${port}"               # donne ${pid}, ${password} et ${token}
```

Une identité est créée une fois par serveur et gardée dans `~/.config/sub-wars-open-sourced/identites.json` :
reconstruire le mod garde le même compte.

Autres possibilités : `from = "bxml/x.bxml"` dans `[[bxml]]` crée un nouveau fichier, copie de celui-ci, et
`copy = { file = "...", select = "..." }` reprend les attributs d'un nœud d'un autre fichier ;
`files = "bxml/pscope_ply??_stats.bxml"` (motif) au lieu de `file` dans `[[bxml]]`, et
`scale = "${facteur}"` qui multiplie tous les nombres des nœuds choisis (après `set`) ;
`if = "${option}"` sur n'importe quelle entrée (appliquée seulement si l'option vaut `oui`), ou
`unless = "${option}"` (seulement si elle vaut `non`) ;
`token_flags = ["triche"]` en tête de recette (annoncé au serveur en ligne dans le jeton) ; `always = true` en tête
de recette : le mod fait partie de toutes les constructions (correctifs du jeu). Toute recette reçoit aussi
`${sdsw_version}`, la version de Sub Wars Open Sourced (fichier `VERSION`, et le nombre de commits dans un dépôt
git : « v0.1.34 »). `[[layout]]` (`file`, `pane`, `width`, `height`) change la taille d'un cadre d'une mise en
page (`layouts/*.arc`) : le jeu comprime en largeur un texte plus large que son cadre.

### Versions du jeu

*Avancement estimé : 100 %.*

Une recette qui patche par adresse (`[[code]]`, `[[amx]]`, `[[shader]]`) dit avec quelles versions du jeu elle
marche ; une recette qui ne touche que des données par leur nom (textes, valeurs BXML) marche avec toutes :

```toml
versions = ["v0", "v5200"]                # en tête de la recette

[[code]]
address = { v0 = 0x00176C8C, v5200 = 0x00177FF0 }    # une table de versions : une valeur par version
expect = "1f402de9"
arm = "bl ${GetUserName}"

[symbols]                                 # des adresses à utiliser dans le code (${GetUserName}), par version
GetUserName = { v0 = 0x0018A458, v5200 = 0x0018FEA4 }
```

N'importe quelle valeur d'une entrée peut être une table de versions (toutes ses clés sont des versions : `v0`,
`v5200`) : `address`, `expect`, `asm_file`, `asm`… `address` peut aussi être un texte comme `"${GetUserName}"`.
Les fichiers lus sont ceux de la version construite : pour la v5200, ceux de la mise à jour d'abord, puis ceux du
jeu. Chaque construction écrit `sdsw.json` (version et mods) dans le dossier du mod : le lanceur voit ainsi quand
les mods installés ne correspondent plus à la version du jeu. Un mod toujours inclus (`always = true`) qui ne
marche pas avec la version construite est laissé de côté, avec un message.

**Plusieurs mods ensemble** : `tools/mod.py build en-ligne triche …` les construit dans un seul dossier
(`build/mods/en-ligne+triche/`), puisqu'Azahar n'en charge qu'un.

Les adresses et les noms viennent de la décompilation (`decomp/`, `ghidra/symbols.txt`) ; les formats sont décrits
dans [../docs/formats.md](../docs/formats.md).

### Code Pawn (`.pasm`)

*Avancement estimé : 95 % — tout le jeu d'instructions, et du Pawn compilé (`tools/pawn2pasm.py`).*

`tools/amxasm.py` assemble du code Pawn (mnémoniques de `decomp/scripts/asm/`) et l'ajoute à la fin d'un
script : rien de ce qui existe ne bouge. `.hook <adresse>` remplace la ou les instructions à cette adresse (8
octets au moins) par un saut vers le code qui suit ; `.original` les rejoue, `.return` revient après elles.
Exemple (le décompte de 120 secondes du salon remplacé par une variable) :

```
.hook 0xebf8                    ; const.alt 0x1d4c0
    push.pri
    push.c "server.bots.countdown"
    sysreq.n sysGetGlobal, 1    ; une native par son nom, et son nombre d'arguments
    move.alt
    pop.pri
    .return
```

Aussi : des fonctions (`nom:` puis `proc` … `retn`, appelées par `call @nom`), `.public @nom` (une
fonction publique de plus), `.var $nom [cellules]`, `.cells $nom 1, 2`, `.string $nom "texte"`, les chaînes
entre guillemets (gardées dans les données du script), les globales du script par leur adresse (`g_504c`),
`float(1.5)`. Une native absente du script est ajoutée à sa table. Voir les `bots_*.pasm` de
[en-ligne](en-ligne/).

Pour du code plus long, on l'écrit en Pawn : `tools/pawn2pasm.py src/x.p` le compile avec le compilateur Pawn 3.3
(`make pawncc`, outil des développeurs) et écrit `x.pasm`, qu'on publie. Les globales du script sont déclarées
`// @game Float:g_1ca0[3]` et ses fonctions `// @call 0x2ea0 nom(paramètres)`. Le code compilé lit et écrit ces
globales à leur vraie adresse, et ses propres données vont à la fin de celles du script (`.data_at`). Les hooks
restent écrits à la main, dans des commentaires `/* asm … */` de la source. Exemple : le pilote des bots,
[`en-ligne/src/bots_ia.p`](en-ligne/src/bots_ia.p) ([../docs/bots.md](../docs/bots.md)).

## Mods disponibles

*Avancement estimé : 100 % — liste à jour.*

| Mod | Versions | Effet |
|---|---|---|
| `correctifs` | v0, v5200 | toujours inclus : corrige le plantage d'Azahar quand une torpille touche un sous-marin sous l'eau |
| `pseudo` | v0, v5200 | toujours inclus : en ligne et en local, votre nom est le pseudo de la console (de l'émulateur), pas « Citra » |
| `version` | toutes | toujours inclus : la version de Sub Wars Open Sourced à la fin de la ligne sous le titre (« … v0.1.34 », même police que la ligne du dessus) |
| `premium` | v0, v5200 | version complète, tous les sous-marins (23, 39 avec la mise à jour), motifs et équipage débloqués, sans l'eShop ([détails](../docs/premium.md)) |
| `missions` | v0, v5200 | les 21 missions du mode solo jouables tout de suite, sans toucher à la sauvegarde |
| `en-ligne` | v0, v5200 (sans bots ni anti-triche) | jeu en ligne sur un serveur [Sub Wars Open Sourced](../server/README.md), avec ses bots pour un joueur seul et des bots qui jouent comme des joueurs ([bots.md](../docs/bots.md)), son anti-triche, la durée des batailles réglée par le serveur et un dialogue qui dit quel serveur est utilisé |
| `specs` | v0, v5200 | vos propres caractéristiques de sous-marins (`tools/subs.py`) ; en ligne, comptées comme triche |
| `mention-titre` | toutes | « © 2026 Nintendo Lawyers » et « Open Sourced by gabrielb0x. » sous le titre (options `ligne1`, `ligne2`) |
| `triche` | v0, v5200 | invincible, torpilles et air infinis, tir sans délai, rechargement rapide, masqueur gratuit, moteur gonflé |
| `vitesse` | toutes | votre sous-marin va 2, 3, 5, 10 ou 15 fois plus vite (option `facteur`) ; en ligne, compté comme triche |
| `texte-titre` | toutes | exemple : « Version gratuite » devient « Version moddée » sur l'écran titre |

« v0 » : le jeu sans sa mise à jour ; « v5200 » : avec la mise à jour ([../docs/mise-a-jour.md](../docs/mise-a-jour.md)).

## Pseudo de la console

*Avancement estimé : 100 % — vérifié dans Azahar.*

Inclus dans tous les mods. En ligne comme en local, le jeu affiche pour chaque joueur le nom de son Mii, que
chaque console envoie aux autres. Sous émulateur, personne n'a de Mii à soi : l'émulateur donne le même à
tout le monde, « Citra ». Le mod remplace ce nom par le **pseudo de la console**, celui que vous réglez dans
l'émulateur (Azahar : Émulation > Configurer > Système > Pseudo ; même réglage dans Citra, Lime3DS,
Mandarine, Borked3DS), 10 caractères au plus. Le visage du Mii ne change pas ; un pseudo vide garde le nom du
Mii. Vérifié dans Azahar : le salon affiche le pseudo de la console au lieu de « Citra ».

## Correctifs

*Avancement estimé : 100 %.*

Inclus dans tous les mods. Sans eux, dans Azahar, une torpille qui touche un sous-marin sous l'eau fige le
jeu, puis Azahar se ferme : il remplit la mémoire (5 Go de RAM et 4 Go d'échange sur une machine de 7 Go)
jusqu'à ce que le système le tue (« Out of memory » dans `journalctl -k`). La cause est un bug du JIT de
shaders d'Azahar, que déclenche l'huile qui fuit d'un sous-marin touché ; le correctif réécrit deux
instructions du shader concerné sans rien changer à l'image. Explication complète :
[../docs/mods.md](../docs/mods.md#correctifs). Vérifié dans Azahar : sans correctif, la mémoire passe de 1,2 à
3,4 Go en 4 secondes dès qu'une nappe d'huile est à l'écran ; avec, elle reste à 1,2 Go et l'huile s'affiche.

```sh
.venv/bin/python tools/mod.py build correctifs --install     # sans aucun autre mod
```

Si vous ne voulez aucun mod, décocher « Enable Shader JIT » dans Azahar (Émulation > Configurer > Graphismes)
évite aussi le bug, au prix d'un émulateur plus lent.

## Toutes les missions

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/mod.py build missions --install
.venv/bin/python tools/mod.py build premium missions --install
```

Le menu des missions ouvre une mission quand les précédentes de sa zone sont terminées, et une zone selon le
nombre total de missions terminées ; en version gratuite, il ne lance que les deux premières zones. Le mod
compte chaque mission comme terminée et ouvre toutes les zones, sans rien écrire dans la sauvegarde : vos
médailles et vos temps restent les vôtres (le total affiché en haut du menu indique 21). Retirer le mod remet
le menu comme avant ; pour marquer les missions terminées pour de bon : `tools/save.py unlock missions`.

## Vitesse du sous-marin

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/mod.py build vitesse --set facteur=5 --install        # 2, 3, 5, 10 ou 15
.venv/bin/python tools/mod.py build premium triche vitesse --set facteur=15 --install
```

Votre sous-marin va `facteur` fois plus vite, en surface, en plongée et en marche arrière, et atteint cette
vitesse dans le même temps qu'avant ; le virage, la plongée et les autres sous-marins ne changent pas. Le mod
multiplie les deux tables qui traduisent les notes de vitesse en accélération (`bxml/table_above_accel` et
`table_below_accel`) : la vitesse maximale du jeu vaut l'accélération fois 25 environ (frottement de 3,8 % par
image). En ligne, le serveur le compte comme de la triche.

## Premium

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/mod.py build premium --install                                     # hors ligne
.venv/bin/python tools/mod.py build en-ligne premium --set server=192.0.2.10 --install      # en ligne
```

La version complète (« premium ») et les cinq sous-marins historiques se vendaient sur l'eShop, fermé depuis
2023. Tout leur contenu est dans le jeu de base, sauf la proue des sous-marins historiques : sans le DLC, leur
pilote voit leur coque à la place (les autres joueurs ne voyaient de toute façon que la coque). Options :
`debloquer` (`oui` : tous les sous-marins, motifs et membres d'équipage sont débloqués dans la sauvegarde) et
`dlc` (`oui` seulement si votre propre DLC est installé dans Azahar : vrais modèles des sous-marins
historiques). Le bouton Boutique recharge le menu. Retirer le mod ne bloque pas la sauvegarde ; une sauvegarde
marquée « premium » par une autre version se répare avec `tools/save.py premium-off`. Fonctionnement :
[../docs/premium.md](../docs/premium.md). En ligne, ce mod ne compte pas comme de la triche.

## Changer les caractéristiques des sous-marins

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/subs.py show                         # les 23 sous-marins et leurs caractéristiques
.venv/bin/python tools/subs.py export                       # votre fichier, avec les valeurs du jeu
.venv/bin/python tools/subs.py set "Type VII" torpedoMax=10 maxTurn=9    # ou éditez le fichier à la main
.venv/bin/python tools/mod.py build premium specs --install
```

Le fichier (`sous-marins.toml`, dans `~/.config/sub-wars-open-sourced/` ; `%APPDATA%\sub-wars-open-sourced\`
sous Windows) liste chaque sous-marin avec ses valeurs commentées : notes de virage, de vitesse en surface et en
plongée, de résistance et de plongée (1 à 10, que le jeu traduit par ses tables `bxml/table_*`), torpilles,
rechargement, cadence de tir, modèle de torpille, places d'équipage, air du masqueur, et quelques réglages fins de
la physique. `tools/subs.py check` dit ce qui diffère du jeu ; les valeurs que le jeu ne supporte pas sont
refusées. Prévu pour le jeu hors ligne : en ligne, le serveur le traite comme la triche.

## Tricher

*Avancement estimé : 100 %.*

```sh
.venv/bin/python tools/mod.py build triche --install                                  # hors ligne
.venv/bin/python tools/mod.py build en-ligne triche --set server=192.0.2.10 --install   # en ligne
.venv/bin/python tools/mod.py build triche --set moteur=non --set rechargement=non --install
```

Options (toutes à `oui` par défaut) : `invincible`, `torpilles`, `air`, `rechargement`, `rafale`, `masqueur`,
`moteur`. Avec `rafale`, chaque appui sur A (ou ZR) tire une torpille, sans délai entre deux tirs ; avec
`torpilles` en plus, le stock ne baisse jamais.
L'invincibilité, les torpilles et l'air infinis reprennent le drapeau `player.muteki` du mode test des
développeurs ; le reste modifie les caractéristiques des 23 sous-marins. Vérifié dans une mission solo :
torpilles qui ne diminuent pas, coque intacte sous les bombes. En ligne, le serveur sait que vous trichez et,
selon sa configuration, ne vous fait jouer qu'avec d'autres tricheurs.

## Jouer en ligne

*Avancement estimé : 95 % — reste : voir les nouveaux bots dans Azahar.*

```sh
make extract                                               # une fois : les fichiers du dump
.venv/bin/python tools/mod.py build en-ligne --set server=192.0.2.10 --install
```

`server` est l'adresse du serveur (IP ou nom, 31 caractères au plus ; `127.0.0.1` par défaut, pour un serveur sur
la même machine) et `port` son port d'authentification (61000 par défaut, le royaume des joueurs sur émulateur).
Pour un serveur chez un ami, son adresse publique : le lanceur de l'ami l'affiche (onglet Serveur), et
`python3 -m sdsw_server.testclient --probe <adresse>` (dans `server/`) vérifie qu'il répond
([../server/README.md](../server/README.md#jouer-avec-des-amis-éloignés)).
Ensuite, dans le jeu : *Multiplayer > Internet Battle*. Le jeu n'a pas besoin d'être modifié : Azahar applique le
patch (`exefs/code.ips`) au lancement.

Pourquoi un patch est nécessaire et ce qu'il change : [../docs/online.md](../docs/online.md).
