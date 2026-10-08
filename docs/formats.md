# File formats

## In-house formats (Vitei)

*Estimated progress: 90 % — all decoded except the data of the raw textures.*

### BXML — binary XML (`.bxml`, 490 files)

*Estimated progress: 100 % — reading and writing, identical byte for byte.*

Read by `source/sys/binxml.cpp` (`BXML::load`, `BXML::initFromData`, `BXML::adjustPointerOffsets`). Turned into XML by
`tools/bxml.py` (`make data` → `extracted/xml/`).

Little endian, offsets from the start of the file (turned into pointers when loading):

| Structure | Fields |
|---|---|
| header | `"BXML"` (`LMXB` on disk), u32 version (1), u32 offset of the root node |
| node (20 bytes) | u32 parent, u32 next sibling, u32 first child, u32 attribute count, u32 offset of the attributes |
| attribute (24 bytes) | u32 type, u32 hash of the name, u32 offset of the name, u32 length of the name, u32 offset of the data, u32 size |

- The first attribute of a node is its **name** (`BXML::Node::getName`). The root is an unnamed document node.
- Types (`BXML::Attribute::set*Data`): 1 name, 2 bytes, 3 string, 4 s16[], 5 s32[], 7 f32[].
- Hash of the names: `generateCRC` = **standard CRC-32** (the same as `zlib.crc32`).

**Writing (XML → BXML)**: `tools/bxml.py --to-bxml file.xml -o file.bxml`. The writer reproduces the layout of
Nintendo's/Vitei's converter, so that an unchanged file comes out **identical byte for byte** (`tools/bxml.py --check`:
490/490):

- header, nodes in pre-order, attribute tables in node order, then a "pool" where each attribute writes its name then
  its data, each padded to 4 bytes;
- texture data (type 2) is aligned to 128 bytes, and so is the pool in these files (except `textures/decal_22` and
  `decal_28`, made by an older version of the tool: `--no-align`);
- a blob whose size is a multiple of 4 reuses the latest identical entry of the pool; the others never do (the
  original tool apparently compares blobs with their padding);
- an attribute without data points at the start of the pool, with a size of zero.

**XML representation** (`make data`): one element per node, one XML attribute per BXML attribute. The type is
deduced from the value: integers → `s32`, numbers written with a point or an exponent → `f32` (always written with a
point: `1200.0`), the rest → string. A prefix gives the type when the deduction would be wrong: `s:31308` is a
string, `hex:...` raw bytes (textures), `s16:` 16-bit integers. In strings, control characters are written `\n` and
`\xHH` (the game's text uses `0x0E` and `0x0C` as formatting codes, e.g. `\x0e(80)`) and the backslash `\\`.

Content: levels (`worlds/`, including the 10 online maps `scope00_online_stage01..10` and their variants `_p1..`),
mode screens (`worlds/mode_*_upper/lower`), statistics of the submarines (`bxml/pscope_ply*_stats`), of the crew
(`worlds/crew_stats`), localised texts (`text/*.bxml`, 1,367 entries per language, EU, US and JP regions), fonts,
textures, and `bxml/buildinfo` (the build's revision: **31308**). In the levels, nodes prefixed with `_`
(`<_actor ...>`) are disabled.

### Levels (`worlds/*.bxml`)

*Estimated progress: 90 % — every element read by `World::readXML`; the properties specific to each actor script
remain to list.*

Read by `World::load` / `World::readXML` (`decomp/src/game/world.cpp`) when a script calls `worldLoad("name", mask)`.
Root `<world>` (attribute `no_idle`: no actor is put to sleep far from the camera), then three passes over its
children:

| Element | Effect |
|---|---|
| `<include file="worlds/x"/>` | reads another level first (recursive): common scenery, preloads |
| `<actor .../>` | takes a free actor (255 at most); every attribute becomes one of its properties (`name`, `script`, `model`, `collshape`, values read by the script...). `level="1 4"`: only exists in these levels (`World::setLevel`) |
| `<dust color min_alpha max_alpha [min_size max_size]/>` | particles floating in the water |
| `<instance model position radius count rand_seed max_angle/>` | copies of a model scattered at random (rocks, seaweed...) |
| `<model file [mem]/>`, `<particle file/>` | model or effect loaded in advance |
| `<light [type="point" position] \| [direction] diffuse ambient specular [env] [name]/>` | a light added to the scene of each active renderer; by default white diffuse and specular, ambient `0x323232` |
| `<fog color density min_depth max_depth [index] [curve] [level]/>` | fog; `curve` = `none`, `linear` (default), `exponent`, `exponent_square` |

Any element may carry `map_mask`: it is only read if `map_mask` is 0 or shares a bit with the mask given to
`worldLoad` (variants of the same map). Unknown elements are ignored.

**Online maps**: each map `scope00_online_stageNN` comes with spawn points `scope00_online_stageNN_pN` (a
`pscope_player` actor: position and bearing in degrees). The game puts each player on point
(node index + `network.randomstartloc`) mod 8 + 1, or, on the maps whose teams start apart (`teamSpawnIndex` of the
`mode_settings` actor), (`randomstartloc` + rank in the team) mod 4 + 1, plus 4 for the second team
(`mode_periscope` `func_540c`).

### Collision: `.hmap` (`hmaps/`, 57 files)

*Estimated progress: 100 %.*

`CollShapeHeightMap::load`: despite the name, a triangle mesh indexed by a quadtree built at load time. Format checked
on the 57 files (exact size, indices < V, normals of length 1).

| Offset | Content |
|---|---|
| 0x00 | `"hmtl"` |
| 0x04 | f32[3] bounding box min, f32[3] max |
| 0x1C | u32 vertex count V, u32 triangle count T |
| 0x24 | V × f32[3] vertices, then T × u32[3] triangle indices, then T × f32[3] unit normals |

### Collision: `.edge` (`edges/`, 58 files, unused)

*Estimated progress: 100 %.*

`CollShapeEdges::load`: 2D outlines in the actor's XY plane (side view), plus a grid of columns to find the nearby
segments quickly. **No level or script of Sub Wars uses them** (no collision shape `type="edges"`; the scenery uses
`hmap`): they are leftovers of the Steel Diver engine, whose original game was a 2D side view.

| Offset | Content |
|---|---|
| 0x00 | `"edge"` |
| 0x04 | f32 width, f32 height, f32 origin X, f32 origin Y (centre of the bounding sphere = origin + size / 2) |
| 0x14 | u32 segment count N, u32 column count M = ⌊width / 16⌋ + 1 |
| 0x1C | N × 32 bytes: f32 x1, y1, x2, y2, length, normal nx, ny, distance to the plane (`nx·x + ny·y`) |
| ... | M × 64 bytes: a column 16 units wide in X; u16 cell count (always 31), then 31 × u16 segment numbers (0 for an empty cell, segment 0 being tested only once) |

The tests (`intersectPoint`, `intersectSphere`, `intersectCapsule`) take the column `(int)(x - originX) >> 4` and only
test its segments. Checked on 56 files (size, unit normals, each listed segment crosses its column).
`enmy_bship_l_coli` and `n2obj_geo01_coli` organise their columns differently (lists without a cell count or fixed
size), which the game's loader would read wrong: made by another version of the tool, and unused too.

### Raw textures (`textures/*.bin`)

*Estimated progress: 50 % — header known; no conversion to an image yet.*

5-byte header: u16 width, u16 height, u8 PICA200 format (0xD = ETC1A4, ...), then the texture data.

### Save

*Estimated progress: 100 % — complete format, editor `tools/save.py`.*

The game has only one save file, `data:/save`, in the title's save archive (under Azahar:
`sdmc/Nintendo 3DS/<id0>/<id1>/title/00040000/000d7e00/data/00000001/save`). It holds the **script globals** whose
name starts with `save` (`sysSetGlobal`, `sysSetGlobalArray`), written by `n_sysSaveDataSave` and read back by
`n_sysSaveDataLoad` (`source/amx/amxsys.cpp`), all little-endian:

```
u32  CRC-32 of everything that follows (generateCRC: zlib's CRC-32), added by FlashMemory::performWrite
u32  version: 27 (the scripts call sysSaveDataLoad("save", 27); another version is ignored)
u32  number of integer values
u32  number of arrays
     integer: name (zero-terminated) + s32
     array: name (zero-terminated) + u32 number of cells + s32 × number
```

The globals live in two hash tables of 4,096 slots (integers at `0x003B9054`, arrays at `0x003BD054`, hash
`h = h * 33 + c` over the first 64 characters): the file's order is the slots' order. A wrong CRC makes the game
format the save again (`amxEventLoadCorruptData`). Floats (best times) are stored as they are, as bits. Main content
(the complete list: `tools/save.py list`):

| Global | Role |
|---|---|
| `save.sub.typenum` | submarine chosen, 1 to 23 |
| `save.sub.unlock[23]`, `save.sub.pattern.unlock[32]`, `save.sub.crew.unlock[32]` | submarines, patterns and crew members unlocked |
| `save.sub.typeN.pattern`, `save.sub.typeN.crew0..4` | pattern and crew (−1: nobody) of each submarine |
| `save.sub.patternN.color0..2` | the three colours (indices of `bxml/swatch_color`) of each pattern; those of a pattern being unlocked come from `bxml/sub_color_set` |
| `save.sub.pattern.new[32]`, `save.sub.crew.new[32]` | "new" badges |
| `save.single.stageS.medal[L]` | medal of mission L of area S: 0 none, 1 completed, 2 gold (time under the target) |
| `save.single.stageS.levelL.time` | best time (float, seconds) |
| `save.sub.enlist` | the full version was seen (see [premium.md](premium.md) and error 098-0101) |
| `save.sub.filteredname[96]`, `save.multi.card000.*` | the player's name, their card (Mii, statistics) |
| `save.multi.*` | online statistics (battles, wins, points, shots...), cards of the other players met |
| `save.sub.extraenabled`, `gyroenabled`, `yinverted`, `morsechatdisable` | settings |

The editor [`tools/save.py`](../tools/save.py) reads and writes this format (summary, unlocks, medals, values one by
one, export and import as JSON), with a backup before every write.

## NintendoWare / SDK formats

*Estimated progress: 25 % — identified; our tools read the shaders (`tools/shbin.py`), the music streams
(`tools/bcstm.py`) and the scripts; models, layouts and fonts remain to decode (PC port).*

| Extension | Format |
|---|---|
| `.bcmdl`, `.bcsdr` | CGFX (NintendoWare models, shaders) |
| `.arc` | darc (NW4C layout archives: `.bclyt`, `.bclim`, `.bclan`) |
| `.bcfnt` | NW4C font (`CFNT`) |
| `.bcsar` | sound archive (`audiores/sound_data.xml`, shipped with the game, lists which sound plays which stream) |
| `.bcstm` | streamed music (`CSTM`): read, decoded (PCM8, PCM16, DSP-ADPCM) and written (PCM8, PCM16) by `tools/bcstm.py`, whose header comment details the layout |
| `.shbin` | compiled PICA200 shaders (`DVLB`); disassembler: `tools/shbin.py` |
| `.amx` | compiled Pawn scripts, see [pawn-scripts.md](pawn-scripts.md) |
| `.mpo` | 3D photos (multi-picture JPEG) |
| `.csid`, `.xml`, `.html` | SoundMaker outputs (C header of the sound IDs, reports) |
