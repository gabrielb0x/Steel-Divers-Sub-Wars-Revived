# La mise à jour v5200

*Avancement estimé : 90 % — la mise à jour s'extrait, s'installe dans Azahar et tous les mods marchent avec elle ;
les bots et l'anti-triche du jeu en ligne restent à voir dans l'émulateur (tableau plus bas).*

Steel Diver: Sub Wars a reçu des mises à jour tant que l'eShop était ouvert. La dernière, en Europe, est le titre
`0004000E000D7E00` en **version 5200** (5.5.0), construite à la révision 33269 du dépôt des développeurs (le jeu
d'origine, « v0 » : révision 31308, `bxml/buildinfo.bxml`). Le projet sait travailler avec les deux versions.

## Ce qu'elle change

*Avancement estimé : 70 % — inventaire des fichiers et du code ; le détail des règles reste à lire.*

- **Un nouvel exécutable** : environ 140 Ko de code en plus (`.text` de 0x251408 à 0x2736AC octets), recompilé :
  toutes les adresses bougent. Les bibliothèques (NEX, Pia, nn::) et la plupart des fonctions du jeu sont les mêmes,
  à leurs nouvelles adresses.
- **Plus de table des symboles** : le `romfs:/map` de la v0 n'est pas dans la mise à jour. Les noms des fonctions
  de la v5200 viennent de la correspondance avec celles de la v0 (même code, adresses des appels et des données
  masquées) : 9338 des 11167 fonctions de la v0 se retrouvent ainsi.
- **16 sous-marins de plus** (n° 24 à 39 : `bxml/pscope_ply24` à `39`, leurs modèles et leurs motifs), **3 cartes
  en ligne** (`worlds/scope00_online_stage11` à `13`), une **mine flottante**, des **torpilles chargées**
  (`surface_torpedo_lv0N_charge`), un écran de personnalisation des sous-marins et une boutique de sous-marins.
- **La boutique change** : la bibliothèque de contenus additionnels gagne des natives (`sysDLCCheckOwned`,
  `sysDLCSetFilterModeSubmarine`, `…CrewExp`, `…Enlist`, `sysDLCIsNewArrival`…) : des sous-marins et de
  l'expérience d'équipage se vendaient à part.
- **Les 123 scripts Pawn sont recompilés** (entre 10 et 30 % de code en plus pour ceux des modes et des
  sous-marins), les textes des 9 langues, 4 polices, 27 mises en page et l'équilibrage de plusieurs sous-marins
  (`pscope_plyNN_stats`) changent.
- **La sauvegarde garde son format** (version 27, `sysSaveDataLoad("save", 27)`).
- **En ligne, le même serveur** : même identifiant de serveur NEX (`0x000D7C00`) et même clé d'accès (`fb9537fe`).

## Comment le jeu lit ses fichiers

*Avancement estimé : 100 %.*

La RomFS de la mise à jour ne contient que les 424 fichiers qu'elle change ou ajoute (38 Mo, contre 1179 fichiers
et 200 Mo pour le jeu). Au démarrage, la v5200 monte deux archives (`0x00103A40`) : `rom:` est la RomFS du jeu
(archive SelfNCCH, type de chemin 0) et `rom2:` celle de la mise à jour (type de chemin 5). Pour chaque fichier, elle
essaie d'abord `rom2:/<fichier>` puis, s'il n'existe pas, `rom:/<fichier>` (`0x00257ACC`).

Les outils font de même : `make extract` (ou l'onglet Jeu du lanceur) extrait la mise à jour dans
`extracted/v5200/` (son `code.bin` et sa RomFS seule), et un fichier de la v5200 se cherche d'abord là, puis dans
`extracted/romfs/` (`tools/versions.py`).

## Dans Azahar

*Avancement estimé : 90 % — reste à jouer longuement à la v5200 dans l'émulateur.*

Une mise à jour s'installe sur la carte SD de la console : dans Azahar, *Fichier > Installer un CIA* avec le `.cia`
**déchiffré** de la mise à jour, ou le bouton *Installer la mise à jour* du lanceur (onglet Jeu), qui écrit les
mêmes fichiers (`sdmc/Nintendo 3DS/…/title/0004000e/000d7e00/content/00000000.tmd` et `00000006.app`). Dès lors,
le jeu démarre en v5200, qu'il soit installé ou ouvert depuis son `.cxi` : Azahar prend le code de la mise à jour
(`AppLoader_NCCH::Load`) et fournit ses deux RomFS.

Le dossier de mods du jeu (`load/mods/00040000000D7E00/`) s'applique aussi à la mise à jour (`GetModId` ramène
`0004000E…` à `00040000…`) : `exefs/code.ips` au code de la mise à jour, `romfs/` aux deux RomFS. Un mod construit
pour la v0 empêcherait donc la v5200 de démarrer (son patch de code tomberait à côté). C'est pourquoi :

- `tools/mod.py` construit pour une version (`--version`, par défaut celle de chaque émulateur trouvé) ;
- chaque mod construit porte un marqueur `sdsw.json` (version et mods) ; le lanceur prévient quand les mods
  installés ne correspondent plus à la version du jeu, et retire ceux de l'autre version quand il installe ou
  retire la mise à jour ;
- chaque recette dit avec quelles versions elle marche (`versions = ["v0", "v5200"]`, voir
  [mods/README.md](../mods/README.md#versions-du-jeu)), et le lanceur l'affiche sur chaque mod.

## Des scripts d'une version à l'autre

*Avancement estimé : 90 % — `tools/amxport.py` apparie 97 % des instructions des 123 scripts (de 70 % pour `hud_pause`
à 100 %) ; les fonctions modifiées restent à lire à la main.*

`tools/amxport.py` dit où est, dans la v5200, une adresse d'un script de la v0 (et inversement, `--reverse`) :

```sh
python3 tools/amxport.py surface_sub 0xcf80 g_1ca0      # 0xcf80 -> 0xf3b8, g_1ca0 -> g_3730
python3 tools/amxport.py --show mode_lobby 0xebf8      # le code autour, les deux versions alignées
python3 tools/amxport.py --stats                       # la part de chaque script appariée
```

Chaque instruction devient un jeton qui ne dépend pas des adresses (cibles de saut et globales masquées, natives par
leur nom, chaînes par leur texte) ; les fonctions sont appariées par leur code identique, leur nom de journal
(`[fichier.inc::fonction]`), les fonctions qu'elles appellent, puis par ressemblance (une mise à jour peut déplacer
un fichier `.inc` entier : celui de `connect.inc` a changé de place dans `mode_internet_menu`) ; deux fonctions
appariées sont alignées instruction par instruction, et chaque globale d'une instruction alignée vote pour son
adresse dans l'autre version. Le pseudo-Pawn de la v5200 s'obtient avec `tools/amxdec.py --version v5200`
(dans `build/scripts-v5200/`, sans les noms de `decomp/pawn/symbols.txt`, qui sont ceux de la v0).

## Une mise à jour chiffrée

*Avancement estimé : 100 %.*

Comme le jeu, la mise à jour doit être **déchiffrée** : Azahar refuse un CIA chiffré, et le projet ne contient
aucune clé de console. Une mise à jour téléchargée telle quelle (ticket de l'eShop) est chiffrée deux fois : par la
clé du titre (couche CIA) puis par les clés NCCH. GodMode9 sur une console, ou un outil de déchiffrement de CIA,
en fait un CIA déchiffré. `tools/extract_cia.py` et le lanceur reconnaissent un CIA de mise à jour encore chiffré
et le disent.

## Les mods et la v5200

*Avancement estimé : 95 % — tous les mods sont portés à la v5200 ; les bots et l'anti-triche du jeu en ligne, portés
par `tools/amxport.py`, restent à voir dans Azahar.*

Les adresses viennent de la correspondance des fonctions (code ARM) et des scripts Pawn entre les deux versions :
même code aux adresses près, ou, pour les fonctions modifiées, alignement instruction par instruction de la
fonction la plus proche.

| Mod | v0 | v5200 | |
|---|---|---|---|
| `correctifs` | ✓ | ✓ | le shader corrigé (`shaders/metaball.shbin`) n'a pas changé |
| `pseudo` | ✓ | ✓ | les mêmes fonctions `FaceSystem`, à leurs adresses de la v5200 |
| `version`, `title-credits`, `title-text` | ✓ | ✓ | textes et mise en page, pris dans les fichiers de la v5200 |
| `premium` | ✓ | ✓ | plus `sysDLCCheckOwned`, les sous-marins 27 à 36 et huit tableaux de déblocage ([premium.md](premium.md#dans-la-mise-à-jour-v5200)) ; vérifié : les 40 membres d'équipage et les sous-marins de la mise à jour débloqués ; les couleurs des motifs ne sont plus perdues à chaque démarrage, et sans le DLC le pilote voit une proue du jeu (la coque de la classe Z cachait la vue) |
| `missions` | ✓ | ✓ | vérifié : toutes les missions et tous leurs niveaux ouverts, le total indique 21 |
| `triche` | ✓ | ✓ | l'invincibilité couvre aussi la mine flottante ; vérifié : tir sans délai, torpilles infinies |
| `vitesse` | ✓ | ✓ | les tables d'accélération n'ont pas changé |
| `specs` | ✓ | ✓ | les 39 sous-marins, dans un fichier à part (`sous-marins-v5200.toml`) : leurs valeurs diffèrent |
| `online` | ✓ | ✓ | connexion au serveur, recherche de partie et dialogue du serveur vérifiés ([online.md](online.md#9-la-mise-à-jour-v5200)) ; bots du serveur et anti-triche portés par `tools/amxport.py` (`*-v5200.pasm`), à voir dans Azahar ; jamais de partie commune entre v0 et v5200 |
