/* Layout checks for ghidra/types.h (32-bit ARM sizes): `make check-types`.
 * Every offset asserted here was verified in the disassembly. */
#include "types.h"
#include <stddef.h>

#define CHECK(cond) _Static_assert(cond, #cond)

CHECK(sizeof(AMX_HEADER) == 0x3c);
CHECK(offsetof(struct tagAMX, codesize) == 0x74);
CHECK(sizeof(AMX) == 0x78);                              /* memclr4(&amx, 0x78) in ScriptAMXLoader::load */

CHECK(offsetof(struct AMXLoader, enabled) == 0xc);      /* AMXLoader::runAll */
CHECK(offsetof(struct AMXLoader, path) == 0xd);         /* ScriptAMXLoader::load */
CHECK(offsetof(struct AMXLoader, name) == 0x8d);        /* AMXLoader::getName */
CHECK(offsetof(struct AMXLoader, eventMessage) == 0x210);
CHECK(offsetof(struct AMXLoader, finished) == 0x214);   /* AMXLoader::isFinished */
CHECK(offsetof(struct AMXLoader, depth) == 0x218);      /* ScriptAMXLoader::callFunction */
CHECK(offsetof(struct AMXLoader, uid) == 0x21c);        /* AMXLoader::getUID */
CHECK(offsetof(struct AMXLoader, index) == 0x220);      /* AMXLoader::registerObserver */
CHECK(offsetof(struct AMXLoader, rendererMask) == 0x224);   /* AMXLoader::setRendererMask */
CHECK(offsetof(struct AMXLoader, actor) == 0x228);      /* AMXLoader::setUserObj */
CHECK(offsetof(struct AMXLoader, hasActor) == 0x22c);
CHECK(offsetof(struct AMXLoader, messages) == 0x230);   /* AMXLoader::preExecute, n_sysSendMessage */
CHECK(offsetof(struct AMXLoader, messagesWritten) == 0x2b0);
CHECK(offsetof(struct AMXLoader, observers) == 0x2b8);  /* AMXLoader::notifyObservers */
CHECK(offsetof(struct AMXLoader, observerCount) == 0x2e0);
CHECK(offsetof(struct AMXLoader, delayed) == 0x2e8);    /* AMXLoader::preExecute, AMXLoader::init */
CHECK(sizeof(AMXDelayedCall) == 0x4c);
CHECK(offsetof(struct AMXLoader, amx) == 0x7a8);        /* ScriptAMXLoader::getAddr */
CHECK(offsetof(struct AMXLoader, memory) == 0x820);     /* ScriptAMXLoader::load / cleanup */
CHECK(offsetof(struct AMXLoader, starting) == 0x824);   /* ScriptAMXLoader::run */
CHECK(offsetof(struct AMXLoader, frozen) == 0x828);     /* ScriptAMXLoader::run */
CHECK(offsetof(struct AMXLoader, publicCache) == 0x848);    /* ScriptAMXLoader::findPublic */
CHECK(sizeof(struct AMXLoader) == 0xcf8);               /* ActorData: CollResult array right after */

CHECK(sizeof(World) == 0xa5f80);                        /* operator new in nnMain */
CHECK(offsetof(World, actorCount) == 0x414);            /* World::getActor */
CHECK(offsetof(World, collisionScene) == 0x418);
CHECK(offsetof(World, collisionDirty) == 0x10420);      /* World::setActorCollisionStateDirty */
CHECK(offsetof(World, recordedCount) == 0x10428);       /* World::postScriptUpdate */
CHECK(offsetof(World, noIdle) == 0x10430);              /* World::readXML */
CHECK(offsetof(World, showFlags) == 0x10434);           /* World::update */
CHECK(offsetof(World, level) == 0x10438);               /* World::getLevel */
CHECK(offsetof(World, replayFramesRemaining) == 0x10440);   /* World::getReplayFramesRemaining */
CHECK(sizeof(ReplayRecord) == 0x24);
CHECK(offsetof(World, replay) == 0x10444);              /* World::updateReplay: frame * 0xB40 + record * 0x24 */
CHECK(sizeof(ReplayExplosion) == 0x194);
CHECK(offsetof(World, explosions) == 0xa3ec4);          /* World::logExplosion */
CHECK(offsetof(World, replayWriteFrame) == 0xa5f5c);
CHECK(offsetof(World, replaying) == 0xa5f68);           /* World::getReplayFramesRemaining */
CHECK(offsetof(World, recordingSuspended) == 0xa5f6a);  /* World::suspendCaching */
CHECK(offsetof(World, visibleGroups) == 0xa5f6c);       /* World::showGroup */
CHECK(offsetof(World, recordedFrames) == 0xa5f70);      /* World::startReplay */

CHECK(sizeof(Actor) == 0x144);                          /* World::init pool stride */
CHECK(offsetof(Actor, idle) == 0x8);                    /* Actor::calcIdle */
CHECK(offsetof(Actor, typeMask) == 0xc);                /* World::findActors */
CHECK(offsetof(Actor, onMap) == 0x24);                  /* World::getMapActors */
CHECK(offsetof(Actor, groups) == 0x38);                 /* World::showGroup */
CHECK(offsetof(Actor, parent) == 0x44);                 /* World::invalidateActor */
CHECK(offsetof(Actor, visible) == 0x64);
CHECK(offsetof(Actor, positionPtr) == 0x6c);
CHECK(offsetof(Actor, idleDistanceSq) == 0x18);         /* Actor::setIdleDistance */
CHECK(offsetof(Actor, id) == 0x34);
CHECK(offsetof(Actor, matrixDirty) == 0x3e);
CHECK(offsetof(Actor, position) == 0x4c);              /* Actor::setPosition */
CHECK(offsetof(Actor, rotation) == 0x58);               /* Actor::setRotation */
CHECK(offsetof(Actor, customFlags) == 0x68);
CHECK(offsetof(Actor, scale) == 0x7c);
CHECK(offsetof(Actor, matrix) == 0xb8);
CHECK(offsetof(Actor, collShapes) == 0xe8);             /* World::clipLine */
CHECK(offsetof(Actor, collShapeCount) == 0xf0);
CHECK(offsetof(Actor, script) == 0x110);                /* Actor::getScript */
CHECK(offsetof(Actor, onCollide) == 0x114);             /* Actor::setScript */
CHECK(offsetof(Actor, onReplayUpdate) == 0x12c);
CHECK(offsetof(Actor, onPausedUpdate) == 0x134);        /* Actor::updatePaused */
CHECK(offsetof(Actor, model) == 0x138);
CHECK(offsetof(Actor, layout) == 0x13c);                /* Actor::update: Layout::animate */
CHECK(offsetof(Actor, data) == 0x140);

CHECK(sizeof(ActorData) == 0x1260);                     /* operator new in the Actor constructor */
CHECK(offsetof(ActorData, lastReadProperties) == 0x108);
CHECK(offsetof(ActorData, name) == 0x188);
CHECK(offsetof(ActorData, stasisScript) == 0x1a8);      /* Actor::setStasisScript */
CHECK(offsetof(ActorData, scriptLoader) == 0x328);
CHECK(offsetof(ActorData, collResults) == 0x1020);      /* CollResult array constructor in Actor */
CHECK(offsetof(ActorData, positionSim) == 0x11e0);
CHECK(offsetof(ActorData, visibleSim) == 0x11f8);
CHECK(offsetof(ActorData, customSim) == 0x11fc);
