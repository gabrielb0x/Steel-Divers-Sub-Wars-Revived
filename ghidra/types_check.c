/* Layout checks for ghidra/types.h (32-bit ARM sizes): `make check-types`.
 * Every offset asserted here was verified in the disassembly. */
#include "types.h"
#include <stddef.h>

#define CHECK(cond) _Static_assert(cond, #cond)

CHECK(sizeof(AMX_HEADER) == 0x3c);
CHECK(offsetof(struct tagAMX, codesize) == 0x74);
CHECK(offsetof(struct AMXLoader, finished) == 0x214);   /* AMXLoader::isFinished */
CHECK(offsetof(struct AMXLoader, amx) == 0x7a8);        /* ScriptAMXLoader::getAddr */

CHECK(sizeof(World) == 0xa5f80);                        /* operator new in nnMain */
CHECK(offsetof(World, actorCount) == 0x414);            /* World::getActor */
CHECK(offsetof(World, collisionScene) == 0x418);

CHECK(sizeof(Actor) == 0x144);                          /* World::init pool stride */
CHECK(offsetof(Actor, idleDistanceSq) == 0x18);         /* Actor::setIdleDistance */
CHECK(offsetof(Actor, id) == 0x34);
CHECK(offsetof(Actor, matrixDirty) == 0x3e);
CHECK(offsetof(Actor, position) == 0x4c);              /* Actor::setPosition */
CHECK(offsetof(Actor, rotation) == 0x58);               /* Actor::setRotation */
CHECK(offsetof(Actor, customFlags) == 0x68);
CHECK(offsetof(Actor, scale) == 0x7c);
CHECK(offsetof(Actor, matrix) == 0xb8);
CHECK(offsetof(Actor, script) == 0x110);                /* Actor::getScript */
CHECK(offsetof(Actor, data) == 0x140);

CHECK(sizeof(ActorData) == 0x1260);                     /* operator new in the Actor constructor */
CHECK(offsetof(ActorData, lastReadProperties) == 0x108);
CHECK(offsetof(ActorData, name) == 0x188);
CHECK(offsetof(ActorData, scriptLoader) == 0x328);
CHECK(offsetof(ActorData, unknown11F8) == 0x11f8);
