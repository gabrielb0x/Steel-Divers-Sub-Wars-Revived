/* Types reconstructed for Steel Diver: Sub Wars, parsed into the Ghidra database by
 * ghidra/scripts/ApplySymbols.java. Plain C only: no #include, no macros. */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef signed char s8;
typedef short s16;
typedef int s32;
typedef long long s64;
typedef float f32;
typedef double f64;

typedef u32 Handle;   /* kernel object handle */
typedef s32 Result;   /* nn::Result: negative on failure */

/* ---- Pawn abstract machine (CompuPhase Pawn 3.3, amx.h; AMX_USERNUM = 4, no JIT) ---- */
typedef s32 cell;
typedef u32 ucell;

typedef struct tagAMX AMX;
typedef cell (*AMX_NATIVE)(AMX *amx, cell *params);
typedef int (*AMX_CALLBACK)(AMX *amx, cell index, cell *result, cell *params);
typedef int (*AMX_DEBUG)(AMX *amx);
typedef int (*AMX_OVERLAY)(AMX *amx, int index);

typedef struct tagAMX_NATIVE_INFO {
    char *name;
    AMX_NATIVE func;
} AMX_NATIVE_INFO;

typedef struct tagAMX_HEADER {
    s32 size;
    u16 magic;
    char file_version;
    char amx_version;
    s16 flags;
    s16 defsize;
    s32 cod;
    s32 dat;
    s32 hea;
    s32 stp;
    s32 cip;
    s32 publics;
    s32 natives;
    s32 libraries;
    s32 pubvars;
    s32 tags;
    s32 nametable;
    s32 overlays;
} AMX_HEADER;

struct tagAMX {
    u8 *base;
    u8 *code;
    u8 *data;
    AMX_CALLBACK callback;
    AMX_DEBUG debug;
    AMX_OVERLAY overlay;
    cell cip;
    cell frm;
    cell hea;
    cell hlw;
    cell stk;
    cell stp;
    int flags;
    long usertags[4];
    void *userdata[4];
    int error;
    int paramcount;
    cell pri;
    cell alt;
    cell reset_stk;
    cell reset_hea;
    cell sysreq_d;
    int ovl_index;
    long codesize;
};

/* ---- Game classes (reconstructed; offsets verified in the disassembly) ---- */
typedef struct AMXLoader AMXLoader;
typedef struct Actor Actor;

/* Per-actor block of 0x1260 bytes allocated by the Actor constructor. */
typedef struct ActorData {
    void *attributes[64];           /* +0x000 BXML::DynamicAttribute*, count at +0x100 */
    u32 attributeCount;             /* +0x100 */
    u32 unknown104;
    char lastReadProperties[0x80];  /* +0x108 (Actor::getLastReadProperties) */
    char name[0x20];                /* +0x188 "Actor" after Actor::init */
    u8 unknown1A8[0x180];
    u8 scriptLoader[0x844];         /* +0x328 ScriptAMXLoader, constructed in place */
    u8 unknownB6C[0x68c];
    u8 unknown11F8;
    u8 pad11F9[3];
    u32 unknown11FC;
    u8 collResults[0x60];           /* CollResult[8], 0x38 bytes each, ends at 0x1260 (see ctor) */
} ActorData;

typedef struct ActorVtbl {
    void *eliminated0;              /* removed by armlink (unused virtual) */
    int (*setAttribute)(Actor *self, void *attribute);
    int (*getAttribute)(Actor *self, void *attribute);
} ActorVtbl;

/* 0x144 bytes; World::init builds a pool of 256 of them, the id is the pool index. */
struct Actor {
    ActorVtbl *vtbl;
    u8 active;                      /* +0x04 slot in use (World::newActor takes the first free one) */
    u8 unknown05;
    u8 unknown06;
    u8 unknown07;
    u8 unknown08;
    u8 unknown09;
    u8 unknown0A;
    u8 isStatic;                    /* +0x0B */
    u32 unknown0C;
    u32 unknown10;
    u32 unknown14;
    f32 idleDistanceSq;             /* +0x18 (Actor::setIdleDistance) */
    f32 idleDistance;               /* +0x1C, 15000.0 by default */
    u32 unknown20;
    u32 unknown24;
    u32 unknown28;
    u32 unknown2C;
    s32 renderer;                   /* +0x30 index of the first active renderer */
    s32 id;                         /* +0x34 */
    u32 unknown38;
    u8 unknown3C;
    u8 unknown3D;
    u8 matrixDirty;                 /* +0x3E set by setPosition/setRotation/scale changes */
    u8 unknown3F;
    u8 unknown40;
    u8 unknown41;
    u8 unknown42;
    u8 unknown43;
    s32 unknown44;
    u8 unknown48;
    u8 pad49[3];
    f32 position[3];                /* +0x4C */
    f32 rotation[3];                /* +0x58 */
    u8 unknown64;
    u8 pad65[3];
    u8 customFlags;                 /* +0x68 (Actor::getCustomFlag) */
    u8 customValues[3];             /* +0x69 (Actor::getCustomValue) */
    f32 *positionPtr;               /* +0x6C points to position */
    f32 previousRotation[3];        /* +0x70 */
    f32 scale[3];                   /* +0x7C */
    u8 unknown88[0x30];
    f32 matrix[12];                 /* +0xB8 MTX34 */
    u8 unknownE8[8];
    u32 unknownF0;
    u32 unknownF4;
    u32 unknownF8[6];
    AMXLoader *script;              /* +0x110 (Actor::getScript) */
    s32 unknown114;
    u32 unknown118[2];
    s32 unknown120;
    u32 unknown124[3];
    s32 unknown130;
    u32 unknown134;
    u32 unknown138;
    u32 unknown13C;
    ActorData *data;                /* +0x140 */
};

/* new World() allocates 0xA5F80 bytes (nnMain). */
typedef struct World {
    Actor *actors[261];             /* +0x000, indexed by actor id (World::getActor) */
    int actorCount;                 /* +0x414 */
    u8 collisionScene[0x1002c];     /* +0x418 CollisionScene */
    u8 actorCache[0x93a80];         /* +0x10444 ActorCacheData[0x41a0], 0x24 bytes each */
    u8 unknownA3EC4[0x1f90];        /* +0xA3EC4 0x14 objects of 0x194 bytes */
    u8 unknownA5E54[0x12c];
} World;

/* Script loader. Slots set to 0 in the vtable were removed by armlink (unused virtuals). */
typedef struct AMXLoaderVtbl {
    void (*init)(AMXLoader *self);
    void (*cleanup)(AMXLoader *self);
    int (*load)(AMXLoader *self, char *name, int stack_size);
    int (*findPublic)(AMXLoader *self, char *name);
    void *eliminated10;
    void (*freezeState)(AMXLoader *self, void *state);
    int (*pushArg)(AMXLoader *self, cell value);
    int (*pushArgArray)(AMXLoader *self, cell *array, int count);
    void (*pushArgString)(AMXLoader *self, char *string);
    cell (*callFunction)(AMXLoader *self, int index);
    void (*thawState)(AMXLoader *self, void *state);
    cell *(*getAddr)(AMXLoader *self, cell amx_addr, int index);
    void (*getString)(AMXLoader *self, char *dest, cell amx_addr);
    void (*setString)(AMXLoader *self, char *src, cell amx_addr);
    void *eliminated38;
} AMXLoaderVtbl;

struct AMXLoader {
    AMXLoaderVtbl *vtbl;
    u8 unknown004[0x210];
    s8 finished;                    /* +0x214 (AMXLoader::isFinished) */
    u8 unknown215[0x593];
    AMX amx;                        /* +0x7A8 (ScriptAMXLoader::getAddr) */
};
