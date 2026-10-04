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
typedef struct Actor Actor;

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
typedef struct AMXLoader AMXLoader;
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
