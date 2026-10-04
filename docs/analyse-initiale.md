# Analyse initiale — Steel Diver: Sub Wars (EUR)

## Le dump

| | |
|---|---|
| Fichier | `votre-dump.cia` |
| Title ID | `00040000000D7E00`, code produit `CTR-N-JNUP`, nom interne `nsub` |
| Version | TMD v0 (version de lancement, sans mise à jour) |
| Contenu 0 | le jeu (CXI), **NoCrypto** : déjà déchiffré, aucune clé de console requise |
| Contenu 1 | manuel électronique (CFA), encore chiffré, inutile pour le projet |

Le `.code` de l'ExeFS est compressé (LZ « backward ») ; une fois décompressé (`extracted/code.bin`, 0x2B5000 octets) :

| Segment | Adresse | Taille |
|---|---|---|
| `.text` | `0x00100000` | `0x251408` (2,3 Mio) |
| `.rodata` | `0x00352000` | `0x0332D0` |
| `.data` | `0x00386000` | `0x02EAE4` |
| `.bss` | `0x003B4AE4` | `0x23EEE4` |

Pile 0x8000, sauvegarde 512 Kio. Services système autorisés (exheader) : `APT:U ac:u boss:U cam:u cecd:u cfg:u
dlp:FKCL dlp:SRVR dsp::DSP frd:u fs:USER gsp::Gpu hid:USER http:C mic:u ndm:u news:u nwm::UDS ptm:u soc:U ssl:C
y2r:u ldr:ro ir:USER nim:aoc am:app`, plus `$hioFIO $hostio0 $hostio1 pxi:dev` (accès debug « host I/O » oubliés).

## La table des symboles du linker (`romfs:/map`)

Les développeurs ont laissé à la racine du RomFS la liste des symboles produite par `armlink` :
**9431 fonctions** avec adresse, taille, nom C++ démanglé et fichier objet / bibliothèque d'origine.

```
0x00100114 3528 nnMain main.o
0x00101118 184 amxSysInit amxsys.o
0x00101c5c 220 DataStreamer::update datastreamer.o
0x00141e94 4 nw::ut::LinkList libnw_snd.fast.a(snd_SoundArchivePlayer.o)
```

Elle couvre 84,7 % du `.text`. Les trous restants sont surtout des fonctions statiques et le runtime C en fin de
segment ; `ghidra/scripts/ScanCodePointers.java` récupère celles qui ne sont atteignables que par des tables de
pointeurs (vtables). Les noms sont parfois tronqués (constructeurs/destructeurs affichés comme `nn::nex::qList`,
fonctions locales nommées `<Func12>`).

Répartition du code :

| Composant | Fonctions | Code | Objets |
|---|---|---|---|
| NEX (auth / matchmaking online) | 2005 | 488 Kio | 11 |
| **Jeu (Vitei)** | **2120** | **389 Kio** | **111** |
| NintendoWare for CTR (`nw::gfx`, `snd`, `lyt`, `font`, `anim`, `ut`) | 1398 | 327 Kio | 197 |
| CTR-SDK (`nn::*`) | 1724 | 263 Kio | 221 |
| Pia (réseau P2P) | 1419 | 245 Kio | 161 |
| `libgles2` (API GL ES du SDK) | 155 | 140 Kio | 15 |
| ImageDb (captures d'écran) | 310 | 59 Kio | 36 |
| `libcfl` (Mii) | 210 | 57 Kio | 8 |
| zlib, runtime armcc, divers | 90 | 43 Kio | 51 |

Le code propre au jeu ne pèse que ~390 Kio : le reste, ce sont des bibliothèques Nintendo.

## Arborescence source d'origine

Les macros d'assert/log du jeu ont laissé `__FILE__` dans le binaire : 44 chemins sont confirmés.

```
source/main.cpp
source/amx/      amxactor amxbb amxloader amxnet amxsys amxutils amxworld
source/effects/  bubbles objectfade
source/game/     actor collision world
source/gfx/      font gfxallocations graphics layout model(.h) renderer scene
source/layouts/  credits
source/net/      connection connectionInternet connectionLocal datarouter datastreamer
                 network rpc session syncevent synclist
source/sys/      allocator binxml dlc exception facesystem flashmemory resource savedata
                 screenshot sdcard system textdata
```

Les ~70 autres objets du jeu (`metaball.o`, `torpedotrail.o`, `DsSubAudioMgr.o`, `eauAudioSystem.o`, …) n'ont pas
de chemin connu : ils sont exportés à la racine de `source/` en attendant d'être classés.

## Architecture du jeu

- **Moteur maison de Vitei** en C++ au-dessus de NintendoWare for CTR et du CTR-SDK.
- **Le jeu est une suite de « modes »** : `nnMain` charge un script Pawn `mode_*` (20 au total : `mode_title`,
  `mode_select`, `mode_lobby`, `mode_periscope`, `mode_shop`…), le fait tourner jusqu'à ce qu'il se termine après
  avoir choisi le mode suivant, puis réinitialise tout (voir `decomp/src/main.cpp`). Boucle verrouillée à 30 fps,
  trois renderers : écran du haut en 3D stéréo, écran du haut en 2D, écran du bas.
- **Logique de jeu scriptée en Pawn** : 123 scripts compilés `romfs:/amx/*.amx` (format AMX file version 10,
  Pawn 3.x, flags `COMPACT|SLEEP`, sans infos de debug ; les fonctions publiques et natives restent nommées, par ex.
  `@actorSync`, `@eventMessage`). Les natives (`amxsys`, `amxactor`, `amxnet`, `amxgfx`, `amxsound`, `amxworld`,
  `amxeffects`…) sont implémentées en C++ dans le jeu, et la VM AMX est celle, open source, de CompuPhase.
- **Données** : `bxml` (XML binaire maison, magic `BXML`), `hmap` (heightmaps, magic `hmtl`), `edge`.
- **Graphismes** : modèles CGFX (`.bcmdl`), layouts NW4C (`.arc` = darc), polices `.bcfnt`, shaders PICA200
  (`.shbin` DVLB, `.bcsdr`), textures brutes `.bin` (en-tête de 5 octets : largeur u16, hauteur u16, format PICA,
  puis les données, souvent en ETC1A4).
- **Audio** : NW4C snd (`.bcsar`, `.bcstm`), plus les fichiers SoundMaker (`.csid` = en-tête C des ID de sons,
  `.xml`, `.html`).
- **Réseau** : NEX 3.x pour l'authentification et le matchmaking (aucune bibliothèque Ranking/DataStore n'est
  liée), Pia pour les parties en P2P (Internet via NEX, local via UDS).

## Inventaire du RomFS (1179 fichiers, 200 Mo)

| Dossier | Fichiers | Taille | Contenu |
|---|---|---|---|
| `audiores/` | 48 | 86 Mo | `.bcstm` (musiques), `sound_data.bcsar` |
| `models/` | 261 | 52 Mo | `.bcmdl` (CGFX) |
| `layouts/` | 76 | 22 Mo | `.arc` (darc NW4C) |
| `hmaps/` | 57 | 13 Mo | `.hmap` |
| `fonts/` | 13 | 8,4 Mo | `.bcfnt`, `.bxml` |
| `textures/` | 130 | 5,5 Mo | 114 `.bxml`, 16 textures brutes `.bin` |
| `edges/` | 58 | 4,7 Mo | `.edge` |
| `text/` | 9 | 4,6 Mo | textes `.bxml` de toutes les régions (EU ×5, US ×3, JP) |
| `amx/` | 123 | 3,0 Mo | scripts Pawn compilés |
| `worlds/` | 221 | 2,9 Mo | `.bxml` (niveaux) |
| `bxml/` | 143 | 1,8 Mo | `.bxml` (configuration, dont `buildinfo.bxml`) |
| `screenshots/` | 10 | 524 Ko | `.mpo` (photos 3D) |
| `shaders/` | 23 | 292 Ko | `.shbin`, `.bcsdr` |
| `audiores_SeaBattle/` | 6 | 116 Ko | `.bcsar` |
| `map` | 1 | 800 Ko | **table des symboles du linker** |

## Online

- Le Nintendo Network a fermé le 8 avril 2024.
- [Pretendo Network](https://github.com/PretendoNetwork/steel-diver-sub-wars) a déjà un serveur NEX pour ce jeu
  (Go, AGPL-3.0) : NEX 3.7.0, clé d'accès `fb9537fe`, protocoles TicketGranting, SecureConnection, NATTraversal,
  MatchMaking, MatchMakingExt et MatchmakeExtension. Il dépend des serveurs de comptes de Pretendo (gRPC).
- Côté client, l'ID du serveur de jeu (`0x000D7C00`), la clé d'accès (en UTF-16) et les paramètres de matchmaking
  sont détaillés dans [online.md](online.md).
