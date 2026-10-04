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

Contenu : niveaux (`worlds/`, dont les 10 cartes en ligne `scope00_online_stage01..10` et leurs variantes `_p1..`),
écrans des modes (`worlds/mode_*_upper/lower`), statistiques des sous-marins (`bxml/pscope_ply*_stats`), de
l'équipage (`worlds/crew_stats`), textes localisés (`text/*.bxml`, 1 367 entrées par langue, régions EU, US et JP),
polices, textures, et `bxml/buildinfo` (révision du build : **31308**). Dans les niveaux, les nœuds préfixés `_`
(`<_actor …>`) sont désactivés.

### Collision : `.hmap` (`hmaps/`, 57 fichiers)

`CollShapeHeightMap::load` : malgré le nom, un maillage de triangles indexé par un quadtree construit au chargement.
Format vérifié sur les 57 fichiers (taille exacte, indices < V, normales de longueur 1).

| Offset | Contenu |
|---|---|
| 0x00 | `"hmtl"` |
| 0x04 | f32[3] boîte englobante min, f32[3] max |
| 0x1C | u32 nombre de sommets V, u32 nombre de triangles T |
| 0x24 | V × f32[3] sommets, puis T × u32[3] indices de triangles, puis T × f32[3] normales unitaires |

### Collision : `.edge` (`edges/`, 58 fichiers)

`CollShapeEdges::load` : contours 2D (plan XZ).

| Offset | Contenu |
|---|---|
| 0x00 | `"edge"` |
| 0x04 | f32 largeur, f32 profondeur, f32 origine X, f32 origine Z |
| 0x14 | u32 nombre de segments N, u32 M |
| 0x1C | N × 32 octets : f32 x1, z1, x2, z2, longueur, normale nx, nz, distance au plan |
| … | données liées à M (structure d'accélération, pas encore décodée) |

### Textures brutes (`textures/*.bin`)

En-tête de 5 octets : u16 largeur, u16 hauteur, u8 format PICA200 (0xD = ETC1A4, …), puis les données de texture.

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
