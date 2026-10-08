# Initial analysis — Steel Diver: Sub Wars (EUR)

## The dump

*Estimated progress: 100 %.*

| | |
|---|---|
| File | the European eShop CIA (one's own dump) |
| Title ID | `00040000000D7E00`, product code `CTR-N-JNUP`, internal name `nsub` |
| Version | TMD v0 (launch version, without update) |
| Content 0 | the game (CXI), **NoCrypto**: already decrypted, no console key needed |
| Content 1 | electronic manual (CFA), still encrypted, useless for the project |

The ExeFS `.code` is compressed (LZ "backward"); once decompressed (`extracted/code.bin`, 0x2B5000 bytes):

| Segment | Address | Size |
|---|---|---|
| `.text` | `0x00100000` | `0x251408` (2.3 MiB) |
| `.rodata` | `0x00352000` | `0x0332D0` |
| `.data` | `0x00386000` | `0x02EAE4` |
| `.bss` | `0x003B4AE4` | `0x23EEE4` |

Stack 0x8000, save 512 KiB. System services allowed (exheader): `APT:U ac:u boss:U cam:u cecd:u cfg:u
dlp:FKCL dlp:SRVR dsp::DSP frd:u fs:USER gsp::Gpu hid:USER http:C mic:u ndm:u news:u nwm::UDS ptm:u soc:U ssl:C
y2r:u ldr:ro ir:USER nim:aoc am:app`, plus `$hioFIO $hostio0 $hostio1 pxi:dev` (forgotten "host I/O" debug access).

## The linker's symbol table (`romfs:/map`)

*Estimated progress: 100 %.*

The developers left at the root of the RomFS the symbol listing produced by `armlink`: **9431 functions** with
address, size, demangled C++ name and object file / library of origin.

```
0x00100114 3528 nnMain main.o
0x00101118 184 amxSysInit amxsys.o
0x00101c5c 220 DataStreamer::update datastreamer.o
0x00141e94 4 nw::ut::LinkList libnw_snd.fast.a(snd_SoundArchivePlayer.o)
```

It covers 84.7 % of `.text`. The remaining holes are mostly static functions and the C runtime at the end of
the segment; `ghidra/scripts/ScanCodePointers.java` recovers those only reachable through tables of pointers
(vtables). Names are sometimes truncated (constructors/destructors shown as `nn::nex::qList`, local functions named
`<Func12>`).

Breakdown of the code:

| Component | Functions | Code | Objects |
|---|---|---|---|
| NEX (online auth / matchmaking) | 2005 | 488 KiB | 11 |
| **Game (Vitei)** | **2120** | **389 KiB** | **111** |
| NintendoWare for CTR (`nw::gfx`, `snd`, `lyt`, `font`, `anim`, `ut`) | 1398 | 327 KiB | 197 |
| CTR-SDK (`nn::*`) | 1724 | 263 KiB | 221 |
| Pia (P2P networking) | 1419 | 245 KiB | 161 |
| `libgles2` (the SDK's GL ES API) | 155 | 140 KiB | 15 |
| ImageDb (screenshots) | 310 | 59 KiB | 36 |
| `libcfl` (Mii) | 210 | 57 KiB | 8 |
| zlib, armcc runtime, misc. | 90 | 43 KiB | 51 |

The game's own code weighs only ~390 KiB: the rest is Nintendo libraries.

## The original source tree

*Estimated progress: 100 % — everything the binary reveals (`__FILE__` paths and object files of the map).*

The game's assert/log macros left `__FILE__` in the binary: 44 paths are confirmed.

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

The ~70 other objects of the game (`metaball.o`, `torpedotrail.o`, `DsSubAudioMgr.o`, `eauAudioSystem.o`, ...) have
no known path: they are exported at the root of `source/` until they are sorted.

## The game's architecture

*Estimated progress: 70 % — loop, modes, world and scripts understood; rendering, sound and low-level networking
only skimmed.*

- **Vitei's in-house engine** in C++ on top of NintendoWare for CTR and the CTR-SDK.
- **The game is a sequence of "modes"**: `nnMain` loads a Pawn script `mode_*` (20 in all: `mode_title`,
  `mode_select`, `mode_lobby`, `mode_periscope`, `mode_shop`...), runs it until it ends after choosing the next
  mode, then resets everything (see `decomp/src/main.cpp`). The loop is locked at 30 fps, with three renderers:
  top screen in stereo 3D, top screen in 2D, bottom screen.
- **Game logic scripted in Pawn**: 123 compiled scripts `romfs:/amx/*.amx` (AMX file version 10, Pawn 3.x, flags
  `COMPACT|SLEEP`, without debug info; the public and native functions keep their names, e.g. `@actorSync`,
  `@eventMessage`). The natives (`amxsys`, `amxactor`, `amxnet`, `amxgfx`, `amxsound`, `amxworld`, `amxeffects`...)
  are implemented in C++ in the game, and the AMX VM is CompuPhase's open-source one.
- **Data**: `bxml` (in-house binary XML, magic `BXML`), `hmap` (heightmaps, magic `hmtl`), `edge`.
- **Graphics**: CGFX models (`.bcmdl`), NW4C layouts (`.arc` = darc), `.bcfnt` fonts, PICA200 shaders (`.shbin`
  DVLB, `.bcsdr`), raw `.bin` textures (5-byte header: width u16, height u16, PICA format, then the data, often
  ETC1A4).
- **Audio**: NW4C snd (`.bcsar`, `.bcstm`), plus the SoundMaker files (`.csid` = C header of the sound IDs,
  `.xml`, `.html`).
- **Networking**: NEX 3.x for authentication and matchmaking (no Ranking/DataStore library is linked), Pia for
  P2P battles (Internet through NEX, local through UDS).

## Inventory of the RomFS (1179 files, 200 MB)

*Estimated progress: 75 % — in-house formats decoded; NintendoWare models, layouts, fonts and sounds only
identified.*

| Folder | Files | Size | Content |
|---|---|---|---|
| `audiores/` | 48 | 86 MB | `.bcstm` (music), `sound_data.bcsar` |
| `models/` | 261 | 52 MB | `.bcmdl` (CGFX) |
| `layouts/` | 76 | 22 MB | `.arc` (NW4C darc) |
| `hmaps/` | 57 | 13 MB | `.hmap` |
| `fonts/` | 13 | 8.4 MB | `.bcfnt`, `.bxml` |
| `textures/` | 130 | 5.5 MB | 114 `.bxml`, 16 raw `.bin` textures |
| `edges/` | 58 | 4.7 MB | `.edge` |
| `text/` | 9 | 4.6 MB | `.bxml` texts of every region (EU ×5, US ×3, JP) |
| `amx/` | 123 | 3.0 MB | compiled Pawn scripts |
| `worlds/` | 221 | 2.9 MB | `.bxml` (levels) |
| `bxml/` | 143 | 1.8 MB | `.bxml` (configuration, including `buildinfo.bxml`) |
| `screenshots/` | 10 | 524 KB | `.mpo` (3D photos) |
| `shaders/` | 23 | 292 KB | `.shbin`, `.bcsdr` |
| `audiores_SeaBattle/` | 6 | 116 KB | `.bcsar` |
| `map` | 1 | 800 KB | **the linker's symbol table** |

## Online

*Estimated progress: 100 % — detailed since in [online.md](online.md), complete protocol and working server.*

- The Nintendo Network closed on 8 April 2024.
- [Pretendo Network](https://github.com/PretendoNetwork/steel-diver-sub-wars) already has a NEX server for this
  game (Go, AGPL-3.0): NEX 3.7.0, access key `fb9537fe`, protocols TicketGranting, SecureConnection, NATTraversal,
  MatchMaking, MatchMakingExt and MatchmakeExtension. It depends on Pretendo's account servers (gRPC).
- On the client side, the game server's ID (`0x000D7C00`), the access key (in UTF-16) and the matchmaking
  parameters are detailed in [online.md](online.md).
