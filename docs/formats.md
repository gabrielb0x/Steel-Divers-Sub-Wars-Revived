# Formats de fichiers

## Formats maison (Vitei)

### BXML — XML binaire (`.bxml`, 490 fichiers)

Lu par `source/sys/binxml.cpp` (`BXML::load`, `BXML::initFromData`, `BXML::adjustPointerOffsets`).
Converti en XML par `tools/bxml.py` (`make data` → `extracted/xml/`).

Little endian, offsets depuis le début du fichier (transformés en pointeurs au chargement) :

| Structure | Champs |
|---|---|
| en-tête | `"BXML"` (`LMXB` sur disque), u32 version (1), u32 offset du nœud racine |
| nœud (20 octets) | u32 parent, u32 frère suivant, u32 premier enfant, u32 nombre d'attributs, u32 offset des attributs |
| attribut (24 octets) | u32 type, u32 hash du nom, u32 offset du nom, u32 longueur du nom, u32 offset des données, u32 taille |

- Le premier attribut d'un nœud est son **nom** (`BXML::Node::getName`). La racine est un nœud document sans nom.
- Types (`BXML::Attribute::set*Data`) : 1 nom, 2 octets, 3 chaîne, 4 s16[], 5 s32[], 7 f32[].
- Hash des noms : `generateCRC` = **CRC-32 standard** (identique à `zlib.crc32`).

**Écriture (XML → BXML)** : `tools/bxml.py --to-bxml fichier.xml -o fichier.bxml`. L'écrivain reproduit la
disposition du convertisseur de Nintendo/Vitei, si bien qu'un fichier non modifié ressort **identique à l'octet près**
(`tools/bxml.py --check` : 490/490) :

- en-tête, nœuds en préordre, tables d'attributs dans l'ordre des nœuds, puis un « pool » où chaque attribut écrit son
  nom puis ses données, chacun complété à 4 octets ;
- les données de texture (type 2) sont alignées sur 128 octets, et le pool aussi dans ces fichiers (sauf
  `textures/decal_22` et `decal_28`, faits par une version plus ancienne de l'outil : `--no-align`) ;
- un bloc dont la taille est un multiple de 4 réutilise la dernière entrée identique du pool ; les autres jamais
  (l'outil d'origine compare visiblement les blocs avec leur remplissage) ;
- un attribut sans données pointe sur le début du pool, avec une taille nulle.

**Représentation XML** (`make data`) : un élément par nœud, un attribut XML par attribut BXML. Le type se déduit de la
valeur : entiers → `s32`, nombres écrits avec un point ou un exposant → `f32` (toujours écrits avec un point : `1200.0`),
le reste → chaîne. Un préfixe donne le type quand la déduction se tromperait : `s:31308` est une chaîne, `hex:…` des
octets bruts (textures), `s16:` des entiers 16 bits. Dans les chaînes, les caractères de contrôle s'écrivent `\n` et
`\xHH` (le texte du jeu utilise `0x0E` et `0x0C` comme codes de mise en forme, par ex. `\x0e(80)`) et la barre
oblique inverse `\\`.

Contenu : niveaux (`worlds/`, dont les 10 cartes en ligne `scope00_online_stage01..10` et leurs variantes `_p1..`),
écrans des modes (`worlds/mode_*_upper/lower`), statistiques des sous-marins (`bxml/pscope_ply*_stats`), de
l'équipage (`worlds/crew_stats`), textes localisés (`text/*.bxml`, 1 367 entrées par langue, régions EU, US et JP),
polices, textures, et `bxml/buildinfo` (révision du build : **31308**). Dans les niveaux, les nœuds préfixés `_`
(`<_actor …>`) sont désactivés.

### Niveaux (`worlds/*.bxml`)

Lus par `World::load` / `World::readXML` (`decomp/src/game/world.cpp`) quand un script appelle
`worldLoad("nom", masque)`. Racine `<world>` (attribut `no_idle` : aucun acteur n'est mis en veille loin de la
caméra), puis trois passes sur ses enfants :

| Élément | Effet |
|---|---|
| `<include file="worlds/x"/>` | lit un autre niveau d'abord (récursif) : décors communs, préchargements |
| `<actor …/>` | prend un acteur libre (255 au plus) ; tous les attributs deviennent ses propriétés (`name`, `script`, `model`, `collshape`, valeurs lues par le script…). `level="1 4"` : n'existe que dans ces niveaux (`World::setLevel`) |
| `<dust color min_alpha max_alpha [min_size max_size]/>` | particules en suspension dans l'eau |
| `<instance model position radius count rand_seed max_angle/>` | copies d'un modèle dispersées au hasard (rochers, algues…) |
| `<model file [mem]/>`, `<particle file/>` | modèle ou effet chargé à l'avance |
| `<light [type="point" position] \| [direction] diffuse ambient specular [env] [name]/>` | lumière ajoutée à la scène de chaque renderer actif ; par défaut diffuse et spéculaire blanches, ambiante `0x323232` |
| `<fog color density min_depth max_depth [index] [curve] [level]/>` | brouillard ; `curve` = `none`, `linear` (défaut), `exponent`, `exponent_square` |

Tout élément peut porter `map_mask` : il n'est lu que si `map_mask` vaut 0 ou partage un bit avec le masque passé à
`worldLoad` (variantes d'une même carte). Les éléments inconnus sont ignorés.

### Collision : `.hmap` (`hmaps/`, 57 fichiers)

`CollShapeHeightMap::load` : malgré le nom, un maillage de triangles indexé par un quadtree construit au chargement.
Format vérifié sur les 57 fichiers (taille exacte, indices < V, normales de longueur 1).

| Offset | Contenu |
|---|---|
| 0x00 | `"hmtl"` |
| 0x04 | f32[3] boîte englobante min, f32[3] max |
| 0x1C | u32 nombre de sommets V, u32 nombre de triangles T |
| 0x24 | V × f32[3] sommets, puis T × u32[3] indices de triangles, puis T × f32[3] normales unitaires |

### Collision : `.edge` (`edges/`, 58 fichiers, inutilisés)

`CollShapeEdges::load` : contours 2D dans le plan XY de l'acteur (vue de côté), plus une grille de colonnes pour
trouver vite les segments proches. **Aucun niveau ni script de Sub Wars ne s'en sert** (aucune forme de collision
`type="edges"` ; les décors utilisent `hmap`) : ce sont des restes du moteur de Steel Diver, dont le jeu d'origine était
en 2D vu de côté.

| Offset | Contenu |
|---|---|
| 0x00 | `"edge"` |
| 0x04 | f32 largeur, f32 hauteur, f32 origine X, f32 origine Y (centre de la sphère englobante = origine + taille / 2) |
| 0x14 | u32 nombre de segments N, u32 nombre de colonnes M = ⌊largeur / 16⌋ + 1 |
| 0x1C | N × 32 octets : f32 x1, y1, x2, y2, longueur, normale nx, ny, distance au plan (`nx·x + ny·y`) |
| … | M × 64 octets : une colonne de 16 unités en X ; u16 nombre de cases (toujours 31), puis 31 × u16 numéros de segments (0 pour une case vide, le segment 0 n'étant testé qu'une fois) |

Les tests (`intersectPoint`, `intersectSphere`, `intersectCapsule`) prennent la colonne `(int)(x - origineX) >> 4` et
ne testent que ses segments. Vérifié sur 56 fichiers (taille, normales unitaires, chaque segment listé recoupe sa
colonne). `enmy_bship_l_coli` et `n2obj_geo01_coli` ont une autre organisation des colonnes (listes sans nombre de
cases ni taille fixe), que le chargeur du jeu lirait mal : produits par une autre version de l'outil, et inutilisés
eux aussi.

### Textures brutes (`textures/*.bin`)

En-tête de 5 octets : u16 largeur, u16 hauteur, u8 format PICA200 (0xD = ETC1A4, …), puis les données de texture.

### Sauvegarde

Le jeu n'a qu'un fichier de sauvegarde, `data:/save`, dans l'archive de sauvegarde du titre (sous Azahar :
`sdmc/Nintendo 3DS/<id0>/<id1>/title/00040000/000d7e00/data/00000001/save`). Il contient les **globales des
scripts** dont le nom commence par `save` (`sysSetGlobal`, `sysSetGlobalArray`), écrites par `n_sysSaveDataSave`
et relues par `n_sysSaveDataLoad` (`source/amx/amxsys.cpp`), le tout en petit-boutiste :

```
u32  CRC-32 de tout ce qui suit (generateCRC : le CRC-32 de zlib), ajouté par FlashMemory::performWrite
u32  version : 27 (les scripts appellent sysSaveDataLoad("save", 27) ; une autre version est ignorée)
u32  nombre de valeurs entières
u32  nombre de tableaux
     entier : nom (terminé par 0) + s32
     tableau : nom (terminé par 0) + u32 nombre de cases + s32 × nombre
```

Les globales vivent dans deux tables de hachage de 4096 cases (entiers en `0x003B9054`, tableaux en `0x003BD054`,
hachage `h = h * 33 + c` sur les 64 premiers caractères) : l'ordre du fichier est celui des cases. Un CRC faux fait
reformater la sauvegarde (`amxEventLoadCorruptData`). Les flottants (meilleurs temps) sont rangés tels quels, en
bits. Contenu principal (la liste complète : `tools/save.py list`) :

| Globale | Rôle |
|---|---|
| `save.sub.typenum` | sous-marin choisi, de 1 à 23 |
| `save.sub.unlock[23]`, `save.sub.pattern.unlock[32]`, `save.sub.crew.unlock[32]` | sous-marins, motifs et membres d'équipage débloqués |
| `save.sub.typeN.pattern`, `save.sub.typeN.crew0..4` | motif et équipage (−1 : personne) de chaque sous-marin |
| `save.sub.patternN.color0..2` | les trois couleurs (indices de `bxml/swatch_color`) de chaque motif ; celles d'un motif qu'on débloque viennent de `bxml/sub_color_set` |
| `save.sub.pattern.new[32]`, `save.sub.crew.new[32]` | pastilles « nouveau » |
| `save.single.stageS.medal[L]` | médaille de la mission L de la zone S : 0 aucune, 1 terminée, 2 or (temps sous l'objectif) |
| `save.single.stageS.levelL.time` | meilleur temps (flottant, secondes) |
| `save.sub.enlist` | la version complète a été vue (voir [premium.md](premium.md) et l'erreur 098-0101) |
| `save.sub.filteredname[96]`, `save.multi.card000.*` | nom du joueur, sa carte (Mii, statistiques) |
| `save.multi.*` | statistiques en ligne (parties, victoires, points, tirs…), cartes des autres joueurs rencontrés |
| `save.sub.extraenabled`, `gyroenabled`, `yinverted`, `morsechatdisable` | réglages |

L'éditeur [`tools/save.py`](../tools/save.py) lit et écrit ce format (affichage, déblocages, médailles, valeurs
une à une, export et import en JSON), avec une copie de sécurité avant chaque écriture.

## Formats NintendoWare / SDK

| Extension | Format |
|---|---|
| `.bcmdl`, `.bcsdr` | CGFX (modèles, shaders NintendoWare) |
| `.arc` | darc (archives de layouts NW4C : `.bclyt`, `.bclim`, `.bclan`) |
| `.bcfnt` | police NW4C (`CFNT`) |
| `.bcsar`, `.bcstm` | archive de sons, musiques en streaming |
| `.shbin` | shaders PICA200 compilés (`DVLB`) |
| `.amx` | scripts Pawn compilés, voir [scripts-pawn.md](scripts-pawn.md) |
| `.mpo` | photos 3D (JPEG multi-image) |
| `.csid`, `.xml`, `.html` | sorties de SoundMaker (en-tête C des ID de sons, rapports) |
