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

/* Script loaders (amxloader.o). AMXLoader is the base class, ScriptAMXLoader the only derived one
 * (it adds the AMX and everything from +0x7A8); the struct below has the derived layout. Slots set
 * to 0 in the vtable were removed by armlink (unused virtuals). */
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

/* Message queued by sysSendMessage(), delivered to the target's @eventMessage(sender, message, value). */
typedef struct AMXMessage {
    int sender;                     /* UID of the sending script */
    u32 target;                     /* target UID | flags << 16 */
    cell message;
    cell value;
} AMXMessage;

/* Call queued by sysCallPublicDelayed(): run when `frames` reaches 0 (AMXLoader::preExecute). */
typedef struct AMXDelayedCall {
    int function;                   /* public index */
    int frames;                     /* 0: free slot */
    int argCount;
    cell args[16];
} AMXDelayedCall;

/* Registers of a suspended script (freezeState / thawState). */
typedef struct AMXState {
    cell frm;
    cell stk;
    cell hea;
    cell pri;
    cell alt;
    cell cip;
    cell reset_stk;
    cell reset_hea;
} AMXState;

struct AMXLoader {
    AMXLoaderVtbl *vtbl;
    AMXLoader *prev;                /* +0x004 list of the loaded scripts, newest first */
    AMXLoader *next;                /* +0x008 */
    u8 enabled;                     /* +0x00C run every frame by AMXLoader::runAll */
    char path[0x80];                /* +0x00D "amx/<name>.amx" */
    char name[0x180];               /* +0x08D */
    u8 pad20D[3];
    int eventMessage;               /* +0x210 index of @eventMessage, -1 if the script has none */
    s8 finished;                    /* +0x214 (AMXLoader::isFinished) */
    u8 ignorePause;                 /* +0x215 still run while the game is paused */
    u8 pad216[2];
    int depth;                      /* +0x218 executions in progress (a native calling back into the script) */
    int uid;                        /* +0x21C sysSetUID(), -1 by default */
    int index;                      /* +0x220 serial number: bit of this loader in the observer sets */
    u32 rendererMask;               /* +0x224 renderers selected while the script runs */
    Actor *actor;                   /* +0x228 actor running the script (setUserObj) */
    u8 hasActor;                    /* +0x22C */
    u8 pad22D[3];
    AMXMessage messages[8];         /* +0x230 ring buffer */
    int messagesWritten;            /* +0x2B0 */
    int messagesRead;               /* +0x2B4 */
    u8 observers[0x26];             /* +0x2B8 bit set of the loaders observing this one (sysObserve) */
    u8 pad2DE[2];
    int observerCount;              /* +0x2E0 */
    int lastObserver;               /* +0x2E4 */
    AMXDelayedCall delayed[16];     /* +0x2E8 */
    /* ScriptAMXLoader */
    AMX amx;                        /* +0x7A8 */
    void *memory;                   /* +0x820 MemBlock holding the AMX image, data, heap and stack */
    u8 starting;                    /* +0x824 next run starts main() instead of resuming */
    u8 pad825[3];
    AMXState frozen;                /* +0x828 registers kept between two frames */
    int publicCache[300];           /* +0x848 public index per global public name id (findPublic) */
};

/* Per-actor block of 0x1260 bytes allocated by the Actor constructor. The "Sim" fields are the
 * simulation copies of values the Actor keeps for drawing (Actor::setVisibleSim ...). */
typedef struct ActorData {
    void *attributes[64];           /* +0x000 BXML::DynamicAttribute*, count at +0x100 */
    u32 attributeCount;             /* +0x100 */
    u32 unknown104;
    char lastReadProperties[0x80];  /* +0x108 (Actor::getLastReadProperties) */
    char name[0x20];                /* +0x188 "Actor" after Actor::init */
    char stasisScript[0x180];       /* +0x1A8 script started when the current one ends (Actor::setStasisScript) */
    AMXLoader scriptLoader;         /* +0x328 the actor's script, a ScriptAMXLoader constructed in place */
    u8 collResults[8][0x38];        /* +0x1020 CollResult[8] (array constructor in Actor) */
    f32 positionSim[3];             /* +0x11E0 simulated state, same layout as Actor +0x4C */
    f32 rotationSim[3];             /* +0x11EC */
    u8 visibleSim;                  /* +0x11F8 */
    u8 pad11F9[3];
    u32 customSim;                  /* +0x11FC custom flags and values */
    u8 unknown1200[0x60];
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
    u8 recorded;                    /* +0x06 recorded in the replay buffer (World::postScriptUpdate) */
    u8 replayed;                    /* +0x07 moved by the replay (World::updateReplay) */
    u8 idle;                        /* +0x08 too far from the camera: not updated (Actor::calcIdle) */
    u8 unknown09;
    u8 unknown0A;
    u8 isStatic;                    /* +0x0B */
    u32 typeMask;                   /* +0x0C matched by the masks of World::findActors & co */
    u32 unknown10;
    u32 unknown14;
    f32 idleDistanceSq;             /* +0x18 (Actor::setIdleDistance) */
    f32 idleDistance;               /* +0x1C, 15000.0 by default */
    u32 unknown20;
    u32 onMap;                      /* +0x24 shown on the map (World::getMapActors) */
    u32 unknown28;
    u32 unknown2C;
    s32 renderer;                   /* +0x30 index of the first active renderer */
    s32 id;                         /* +0x34 */
    u32 groups;                     /* +0x38 visibility groups (World::showGroup) */
    u8 unknown3C;
    u8 unknown3D;
    u8 matrixDirty;                 /* +0x3E set by setPosition/setRotation/scale changes */
    u8 unknown3F;
    u8 unknown40;
    u8 unknown41;
    u8 unknown42;
    u8 unknown43;
    s32 parent;                     /* +0x44 actor id, -1: none (actorSetParent, World::invalidateActor) */
    u8 unknown48;
    u8 pad49[3];
    f32 position[3];                /* +0x4C drawn state: position, rotation, visible, custom (0x20 bytes) */
    f32 rotation[3];                /* +0x58 */
    u8 visible;                     /* +0x64 (actorIsVisibleDraw) */
    u8 pad65[3];
    u8 customFlags;                 /* +0x68 (Actor::getCustomFlag) */
    u8 customValues[3];             /* +0x69 (Actor::getCustomValue) */
    f32 *positionPtr;               /* +0x6C simulated state: the drawn one or ActorData +0x11E0 (*Sim functions) */
    f32 previousRotation[3];        /* +0x70 */
    f32 scale[3];                   /* +0x7C */
    u8 unknown88[0x30];
    f32 matrix[12];                 /* +0xB8 MTX34 */
    void *collShapes[2];            /* +0xE8 CollShape* (World::update, World::clipLine) */
    int collShapeCount;             /* +0xF0 */
    u32 unknownF4;
    u32 unknownF8[6];
    AMXLoader *script;              /* +0x110 (Actor::getScript); public functions below, -1: absent */
    int onCollide;                  /* +0x114 @eventCollide, or @eventCollideTag (Actor::setScript) */
    int onUpdate;                   /* +0x118 @update */
    int onVisibleUpdate;            /* +0x11C @visibleUpdate */
    int onNotVisibleUpdate;         /* +0x120 @notVisibleUpdate */
    int onReplayEnter;              /* +0x124 @replayEnter */
    int onReplayExit;               /* +0x128 @replayExit */
    int onReplayUpdate;             /* +0x12C @replayUpdate */
    int callOnce;                   /* +0x130 called at the next Actor::update, then -1 */
    int onPausedUpdate;             /* +0x134 @pausedUpdate */
    void *model;                    /* +0x138 ModelSet */
    void *layout;                   /* +0x13C Layout (2D interface) */
    ActorData *data;                /* +0x140 */
};

/* One actor in one frame of the replay buffer (World::postScriptUpdate records, updateReplay plays). */
typedef struct ReplayRecord {
    s32 actor;                      /* index in actors[], -1: unused */
    f32 position[3];
    f32 rotation[3];
    u8 visible;
    u8 pad19[3];
    u32 custom;                     /* the actor's custom flags and values */
} ReplayRecord;

/* Explosion logged for the replays (World::logExplosion), re-created when the replay reaches it. */
typedef struct ReplayExplosion {
    s32 frame;                      /* replay frame, -1: free slot */
    char properties[0x180];         /* properties file of the explosion actor */
    f32 position[3];
    s32 type;
} ReplayExplosion;

/* new World() allocates 0xA5F80 bytes (nnMain); g_world points to it (World::init). */
typedef struct World {
    Actor *actors[261];             /* +0x000, indexed by actor id; 256 created, id 0 is never handed out */
    int actorCount;                 /* +0x414 */
    u8 collisionScene[0x10008];     /* +0x418 CollisionScene */
    u8 *collisionDirty;             /* +0x10420 one flag per actor (setActorCollisionStateDirty) */
    int updatedCount;               /* +0x10424 actors updated this frame */
    int recordedCount;              /* +0x10428 actors recorded in the replay this frame (80 at most) */
    int idleCount;                  /* +0x1042C */
    u8 noIdle;                      /* +0x10430 <world no_idle> */
    u8 pad10431[3];
    u32 showFlags;                  /* +0x10434 debug display: 1 bounds, 2 collision shapes */
    int level;                      /* +0x10438 an actor with a "level" attribute only exists in those levels */
    u32 unknown1043C;
    int replayFramesRemaining;      /* +0x10440 */
    ReplayRecord replay[210][80];   /* +0x10444 the last 210 frames: 7 seconds at 30 fps */
    ReplayExplosion explosions[20]; /* +0xA3EC4 */
    u8 unknownA5E54[0x108];
    int replayWriteFrame;           /* +0xA5F5C */
    int replayOldestFrame;          /* +0xA5F60 */
    int replayReadFrame;            /* +0xA5F64 */
    u8 replaying;                   /* +0xA5F68 engine global "player.isReplay" */
    u8 replayEnds;                  /* +0xA5F69 0: the replay loops */
    u8 recordingSuspended;          /* +0xA5F6A (World::suspendCaching) */
    u8 padA5F6B;
    u32 visibleGroups;              /* +0xA5F6C (World::showGroup), all by default */
    u32 recordedFrames;             /* +0xA5F70 */
    u8 unknownA5F74[0xC];
} World;


/* ---- Shop and add-on contents (source/sys/dlc.cpp; decomp/src/sys/dlc.cpp, docs/premium.md) ----
 * One instance (getNsubShop: 0x005920B8). Item n of the add-on content title is content n: 91 is the
 * full version, 1..5 the historical submarines. */
typedef struct NsubShopItem {
    u8 data[0x300];                  /* name, description, price, dates... for the shop scripts (sysDLCGetItem*) */
} NsubShopItem;

typedef struct NsubShop {
    void *vtable;                    /* 0x00376B10 */
    u8 busy;                         /* +0x04 an asynchronous request runs (sysDLCWaitThread) */
    u8 _pad05[3];
    u32 thread[2];                   /* +0x08 nn::os::Thread running exec() (NsubThread::callFromThread) */
    s32 request;                     /* +0x10 1 content set list, 2 balance, 3 delete an item, 4 server time */
    u32 lastResult[2];               /* +0x14 nn::ec::CTR::ResultError (sysDLCCheckLastResult) */
    u32 applet;                      /* +0x1C nn::ec::CTR::EcApplet */
    u32 session;                     /* +0x20 nn::ec::CTR::Session */
    u32 server;                      /* +0x24 nn::ec::CTR::Server */
    u32 eshopId[2];                  /* +0x28 {unique id, 0x2F0002} (initializeEc) */
    u32 dataTitle[2];                /* +0x30 {unique id, 0x2F0000}: the add-on content title */
    u8 _pad38[8];
    u8 metaData[0x50];               /* +0x40 nn::ec::CTR::MetaDataReader (+0x40/+0x44: mounted) */
    void *catalog;                   /* +0x90 nn::ec::CTR::ContentSetCatalog (createCatalog) */
    void *catalogMemory;             /* +0x94 1 MB */
    void *filterMemory;              /* +0x98 4 KB */
    s32 catalogOffset;               /* +0x9C */
    NsubShopItem items[5];           /* +0xA0 */
    u32 owned[4];                    /* +0xFA0 bitmap of the owned contents 0..127 (updateCondition) */
    u8 balance[0x20];                /* +0xFB0 nn::ec::CTR::Server::GetBalance */
    char balanceText[0x80];          /* +0xFD0 ConvertPrice */
    s32 deleteIndex;                 /* +0x1050 deleteItemAsync */
    void *contentArchiveMemory;      /* +0x1054 mountContentArchive */
    u8 contentArchiveMounted;        /* +0x1058 "content:" is mounted */
    u8 _pad1059[7];
    u8 serverTime[8];                /* +0x1060 nn::fs::DateTime (getServerTimeAsync) */
    char filter[4][0x40];            /* +0x1068 "==", "string", "ITEM_TYPE", the item type */
    u8 _pad1168[0x40];
    s32 filterMode;                  /* +0x11A8 sysDLCSetFilterMode*: which item type the shop lists */
} NsubShop;
