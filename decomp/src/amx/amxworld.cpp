// source/amx/amxworld.cpp (amxworld.o): the world natives of the scripts (table natives_World, registered
// by amx_WorldInit 0x00171970). They return actor ids (0: none) and work on the global world (g_world,
// 0x0038E2B4; game/world.cpp). Prototypes: decomp/pawn/natives.inc.
//
// Reconstructed by hand from decomp/raw/source/amx/amxworld.cpp and the disassembly. Not compilable on its
// own. Vectors are read with AMXLoader::getVector3 (3 cells of the script).

static int id(Actor *a) { return a != nullptr ? a->id : 0; }

static cell n_worldLoad(AMX *, const cell *p)                // 0x0032B68C: worlds/<name>.bxml
{
	char name[384];
	AMXLoader::getCurrentLoader()->getString(name, p[1]);
	g_world->load(name, p[2]);
	return 0;
}

static cell n_worldNewActor(AMX *, const cell *) { return id(g_world->newActor()); }          // 0x0032B764
static cell n_worldKillActors(AMX *, const cell *) { g_world->killActors(); return 0; }       // 0x0032B654
static cell n_worldKillActorsByLevel(AMX *, const cell *) { g_world->killActorsByLevel(); return 0; }  // 0x0032B670
static cell n_worldSetLevel(AMX *, const cell *p) { g_world->setLevel(p[1]); return 0; }     // 0x0032B7C4 ("[amxorld::worldSetLevel] Level %d")

static cell n_worldFindActor(AMX *, const cell *p)           // 0x0032B33C: by name
{
	char name[384];
	AMXLoader::getCurrentLoader()->getString(name, p[1]);
	return id(g_world->findActor(name));
}

static cell n_worldFindActorUID(AMX *, const cell *p) { return id(g_world->findActorUID(p[1])); }   // 0x0032B38C

// 0x0032B3B8 / 0x0032B42C: worldFindActors(found[], center[3], Float:radius, mask, max): the visible actors
// of type & mask within radius; returns how many. worldFindActorsSorted takes (max, mask) in the other
// order — surface_torpedo_p_homing calls it as (..., mask, 10): its search runs with mask 10 (0x2 | 0x8:
// the player and the computer subs' torpedoes) and the intended mask (2, or 0x80004) as maximum — and it
// is not sorted (world.cpp).
static cell n_worldFindActors(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	cell *found = self->getAddr(p[1], 0);
	VEC3 center = self->getVector3(p[2]);
	return g_world->findActors(found, center, amx_ctof(p[3]), p[4], p[5]);
}

static cell n_worldFindActorsSorted(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	cell *found = self->getAddr(p[1], 0);
	VEC3 center = self->getVector3(p[2]);
	return g_world->findActorsSorted(found, center, amx_ctof(p[3]), p[4], p[5]);   // max = p[4], mask = p[5]
}

// 0x0032B4A0: worldFindClosestActor(position[3], unused, mask).
static cell n_worldFindClosestActor(AMX *, const cell *p)
{
	VEC3 position = AMXLoader::getCurrentLoader()->getVector3(p[1]);
	return id(g_world->findClosestActor(position, p[3]));
}

// 0x0032B4E8 / 0x0032B5A8: every actor of type & mask, the map's actors.
static cell n_worldGetActors(AMX *, const cell *p) { return g_world->getActors(AMXLoader::getCurrentLoader()->getAddr(p[1], 0), p[3], p[2]); }
static cell n_worldGetMapActors(AMX *, const cell *p) { return g_world->getMapActors(AMXLoader::getCurrentLoader()->getAddr(p[1], 0), p[2]); }

// 0x0032B2DC: worldClipLine(from[3], direction[3], Float:length, mask): the distance to the first hit.
static cell n_worldClipLine(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	VEC3 from = self->getVector3(p[1]);
	VEC3 direction = self->getVector3(p[2]);
	return amx_ftoc(g_world->clipLine(from, direction, amx_ctof(p[3]), p[4]));
}

// 0x0032B528: Float:worldGetHeightAt(Float:x, Float:z, Float:normal[3], mask).
static cell n_worldGetHeightAt(AMX *, const cell *p)
{
	cell *out = AMXLoader::getCurrentLoader()->getAddr(p[3], 0);
	VEC3 v;
	f32 height = g_world->getHeightAt(amx_ctof(p[1]), amx_ctof(p[2]), &v, p[4]);
	memcpy(out, &v, sizeof v);
	return amx_ftoc(height);
}

// 0x0032B6DC: worldLogExplosion(type[], position[3], value), into the replay ("[World::logExplosion] ...").
static cell n_worldLogExplosion(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char type[384];
	self->getString(type, p[1]);
	g_world->logExplosion(type, self->getVector3(p[2]), p[3]);
	return 0;
}

// The replay of the last seconds (world.cpp).
static cell n_worldStartReplay(AMX *, const cell *p) { g_world->startReplay(p[1], p[2]); return 0; }          // 0x0032B890
static cell n_worldIsPlayingReplay(AMX *, const cell *) { return g_world->replaying; }                        // 0x0032B638
static cell n_worldGetReplayFrameID(AMX *, const cell *) { return g_world->recordedFrames; }                  // 0x0032B5E4
static cell n_worldGetReplayFramesRemaining(AMX *, const cell *) { return g_world->getReplayFramesRemaining(); }  // 0x0032B600
static cell n_worldSetCachingMovement(AMX *, const cell *p) { g_world->setCachingMovement(p[1] != 0, p[2]); return 0; }  // 0x0032B784
static cell n_worldSuspendCache(AMX *, const cell *) { g_world->suspendCaching(); return 0; }                 // 0x0032B8C4
static cell n_worldCacheSuspended(AMX *, const cell *) { return 0; }                                          // 0x0032B2D4

// Groups of actors shown or hidden together.
static cell n_worldShowGroup(AMX *, const cell *p) { g_world->showGroup(p[1], p[2] != 0); return 0; }         // 0x0032B860
static cell n_worldIsGroupVisible(AMX *, const cell *p) { return g_world->visibleGroups & p[1]; }             // 0x0032B610
static cell n_worldSetShowFlags(AMX *, const cell *p) { g_world->showFlags = p[1]; return 0; }                // 0x0032B83C
