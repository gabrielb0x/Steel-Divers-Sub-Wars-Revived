// source/game/world.cpp (world.o): the world of a mode: actor pool, levels, replays.
//
// Reconstructed by hand from decomp/raw/source/game/world.cpp and the disassembly; the layouts of
// World, Actor and the replay records are in ghidra/types.h. Not compilable on its own.
// Left out: World::setCachingMovement (0x002E5928, Ghidra fails on it), World::getHeightAt and
// World::startReplay (parameters not identified yet), and the Actor constructor that armlink
// placed in this object (see actor.cpp).
//
// nnMain creates one World per mode. It owns a fixed pool of 256 actors (id = index; id 0 is never
// handed out, so that 0 can mean "the calling actor" in the scripts), the collision scene, and a
// replay buffer of the last 210 frames: the "replay" of the game rewinds up to 7 seconds and
// replays the recorded positions, re-creating the explosions logged by the scripts.

World *g_world;         // 0x0038E2B4
f32 g_worldTime;        // 0x0038E2B0: seconds of play, advanced by a fixed step

enum { MAX_ACTORS = 256, REPLAY_FRAMES = 210, REPLAY_ACTORS = 80, REPLAY_EXPLOSIONS = 20 };

// 0x001031B4: once per mode, right after `new World()` (nnMain).
void World::init()
{
	actorCount = 0;
	recordingSuspended = false;
	CollisionScene::init(&collisionScene);
	g_world = this;

	Actor *pool = new Actor[MAX_ACTORS];   // 0x144 bytes each
	for (int i = 0; i < MAX_ACTORS; i++) {
		Actor *actor = &pool[i];
		actor->setActive(false);
		actor->id = actorCount;
		collisionScene.setActorDirty(actorCount);
		actors[actorCount++] = actor;
	}

	noIdle = false;
	g_worldTime = 0;
	showFlags = 0;
	level = 0;
	for (int i = 0; i < REPLAY_EXPLOSIONS; i++) {
		explosions[i].frame = -1;
	}
	replayWriteFrame = 0;
	replayOldestFrame = 0;
	replayReadFrame = 0;
	replaying = false;
	amxSysSetGlobal("player.isReplay", replaying);
	visibleGroups = 0xFFFFFFFF;
}

// 0x00103354: the simulation step, before the scripts run (nnMain).
void World::update(const VEC3 *cameraPos)
{
	bool paused = System::isPaused();
	if (!paused) {
		g_worldTime += 1.0f / 30;     // fixed step: the game is locked at 30 fps
	}
	Renderer::setShowBounds(showFlags & 1);

	updatedCount = 0;
	recordedCount = 0;
	idleCount = 0;
	for (int i = 0; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (!actor->active) {
			continue;
		}
		if (!actor->idle) {
			if (!paused) {
				actor->update();
			} else {
				actor->updatePaused();
			}
		}
		if (actor->calcIdle(cameraPos)) {
			idleCount++;
		}
		if (g_world->showFlags & 2) {
			for (int k = 0; k < actor->collShapeCount; k++) {
				actor->collShapes[k]->vtbl[0](actor->collShapes[k], actor);   // probably draw()
			}
		}
		updatedCount++;
	}

	if (!System::isPaused()) {
		collisionScene.updateActors();
		collisionScene.processCollisions();
	}
}

// 0x00103084: after the scripts: matrices for drawing, then the replay buffer.
void World::postScriptUpdate(const VEC3 *cameraPos)
{
	bool paused = System::isPaused();
	for (int i = 0; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (!actor->active) {
			continue;
		}
		if (!actor->idle) {
			actor->updateMatrix();
			actor->calcVisible();
		}
		if (!paused && actor->recorded && recordedCount < REPLAY_ACTORS) {
			ReplayRecord &record = replay[replayWriteFrame][recordedCount++];
			const f32 *sim = actor->positionPtr;    // simulated state: position, rotation, visible, custom
			record.actor = i;
			record.position = VEC3(sim[0], sim[1], sim[2]);
			record.rotation = *(VEC3 *)actor->rotationSim();
			record.visible = *(u8 *)(sim + 6);
			record.custom = *(u32 *)(sim + 7);
		}
	}
	if (!paused) {
		updateReplay();
	}
}

// 0x0010CDE8
void World::updateReplay()
{
	if (replaying) {
		if (replayFramesRemaining == 0) {
			// End of the replay: it loops unless replayEnds is set.
			replaying = !replayEnds;
			amxSysSetGlobal("player.isReplay", false);
			if (replayEnds) {
				for (int i = 0; i < actorCount; i++) {
					if (actors[i]->active) {
						actors[i]->replayEnded();
					}
				}
			}
			if (!replaying) {
				goto record;
			}
		}
		for (int k = 0; k < REPLAY_ACTORS; k++) {
			ReplayRecord &record = replay[replayReadFrame][k];
			if (record.actor == -1) {
				continue;
			}
			Actor *actor = actors[record.actor];
			if (actor->replayed) {
				actor->setVisible(record.visible);
				*(u32 *)&actor->customFlags = record.custom;
				actor->setPosition(record.position);
				actor->setRotation(record.rotation);
			}
			record.actor = -1;
		}
		checkExplosion(replayReadFrame, true);
		if (++replayReadFrame == REPLAY_FRAMES) {
			replayReadFrame = 0;
		}
		replayFramesRemaining--;
	}

record:
	if (!recordingSuspended) {
		// Next frame of the ring buffer. Its records are cleared from the count of the frame just
		// recorded: if the next frame records fewer actors, stale records stay (as in the binary).
		if (++replayWriteFrame == REPLAY_FRAMES) {
			replayWriteFrame = 0;
		}
		for (int k = recordedCount; k < REPLAY_ACTORS; k++) {
			replay[replayWriteFrame][k].actor = -1;
		}
		if (replayWriteFrame == replayOldestFrame && ++replayOldestFrame == REPLAY_FRAMES) {
			replayOldestFrame = 0;
		}
		checkExplosion(replayWriteFrame, false);    // forgets the explosions of the overwritten frame
		recordedFrames++;
	}
}

// 0x0011703C: explosions logged for `frame`: freed, and re-created if `create` (replay).
void World::checkExplosion(int frame, bool create)
{
	for (int i = 0; i < REPLAY_EXPLOSIONS; i++) {
		ReplayExplosion &explosion = explosions[i];
		if (explosion.frame != frame) {
			continue;
		}
		explosion.frame = -1;
		if (!create) {
			continue;
		}
		Actor *actor = newActor();     // inlined, including the "Out of Actors. Max: %d" listing
		actor->readProperties(explosion.properties, NULL);
		actor->setPosition(explosion.position);
		actor->updateMatrix();
		actor->setAttribute(DynamicProperty("type", explosion.type));
		actor->setAttribute(DynamicProperty("expPos", explosion.position));
		actor->setAttribute(DynamicProperty("localOnly", 1));
	}
}

// 0x002E54F8: worldLogExplosion(properties, position, type), so that replays show it.
void World::logExplosion(const char *properties, const VEC3 &position, int type)
{
	for (int i = 0; i < REPLAY_EXPLOSIONS; i++) {
		if (explosions[i].frame == -1) {
			explosions[i].frame = replayWriteFrame;
			strncpy(explosions[i].properties, properties, sizeof(explosions[i].properties));
			explosions[i].position = position;
			explosions[i].type = type;
			return;
		}
	}
	// (log of a full table, patched out: "source/game/world.cpp", line 765)
}

// 0x002E6DC4: first free actor of the pool, initialised; NULL when all 255 are in use.
Actor *World::newActor()
{
	for (int i = 1; i < actorCount; i++) {
		if (!actors[i]->active) {
			actors[i]->init();
			collisionScene.setActorDirty(i);
			return actors[i];
		}
	}
	// Leftover of a debug listing of the actors ("STATIC " + script name), log patched out.
	return NULL;
}

// 0x002455A0
Actor *World::getActor(int id)
{
	return id > 0 && id < actorCount ? actors[id] : NULL;
}

// 0x00218DA0: by the actor's name (ActorData::name, the "name" property).
Actor *World::findActor(const char *name)
{
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && strcmp(actors[i]->data->name, name) == 0) {
			return actors[i];
		}
	}
	return NULL;
}

// 0x002E5430: by the UID of the actor's script (its id when it has no script).
Actor *World::findActorUID(int uid)
{
	for (int i = 1; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (actor->active && (actor->script ? actor->script->uid : actor->id) == uid) {
			return actor;
		}
	}
	return NULL;
}

// 0x002E51E8: visible actors of `mask` within `radius`; returns how many ids were written.
int World::findActors(int *found, const VEC3 &center, f32 radius, int max, u32 mask)
{
	int count = 0;
	for (int i = 1; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (actor->active && (actor->typeMask & mask) && actor->visible
				&& distanceSq(*(VEC3 *)actor->positionPtr, center) < radius * radius) {
			found[count++] = actor->id;
			if (count >= max) {
				break;
			}
		}
	}
	return count;
}

// 0x002E5650: same, sorted by distance (bubble sort).
int World::findActorsSorted(int *found, const VEC3 &center, f32 radius, int max, u32 mask);

// 0x002E578C
Actor *World::findClosestActor(const VEC3 &position, u32 mask)
{
	Actor *closest = NULL;
	f32 best = FLT_MAX;
	for (int i = 1; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (actor->active && (actor->typeMask & mask)) {
			f32 d = distanceSq(*(VEC3 *)actor->positionPtr, position);
			if (d < best) {
				closest = actor;
				best = d;
			}
		}
	}
	return closest;
}

// 0x002E6F04
int World::getActors(int *found, int max, u32 mask)
{
	int count = 0;
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && (actors[i]->typeMask & mask)) {
			found[count++] = actors[i]->id;
			if (count >= max) {
				break;
			}
		}
	}
	return count;
}

// 0x002E5498: the actors drawn on the map.
int World::getMapActors(int *found, int max)
{
	int count = 0;
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && actors[i]->onMap) {
			found[count++] = actors[i]->id;
			if (count >= max) {
				break;
			}
		}
	}
	return count;
}

// 0x002E528C: kills the actors of the last active renderer.
void World::killActors()
{
	int renderer = 0;
	for (int i = 0; i < Renderer::getNumRenderers(); i++) {
		if (Renderer::getRenderer(i)->isActive()) {
			renderer = i;
		}
	}
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && actors[i]->renderer == renderer) {
			actors[i]->kill();
		}
	}
}

// 0x00243074: an actor is gone: its children lose their parent.
void World::invalidateActor(int id)
{
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && actors[i]->parent == id) {
			actors[i]->parent = -1;
		}
	}
}

// 0x002E6CF4: collision of the segment [from, from + direction * length] with the shapes of the
// actors of `mask` (each shape clips the end point).
void World::clipLine(const VEC3 &from, const VEC3 &direction, f32 length, u32 mask)
{
	VEC3 to = from + direction * length;
	for (int i = 1; i < actorCount; i++) {
		Actor *actor = actors[i];
		if (actor->active && (actor->typeMask & mask)) {
			for (int k = 0; k < actor->collShapeCount; k++) {
				actor->collShapes[k]->clipLine(from, &to, direction);   // vtable slot 0x2C
			}
		}
	}
}

// 0x002E6FC8
void World::showGroup(u32 groups, bool show)
{
	visibleGroups = show ? visibleGroups | groups : visibleGroups & ~groups;
	for (int i = 1; i < actorCount; i++) {
		if (actors[i]->active && (actors[i]->groups & groups)) {
			actors[i]->changeVisOnGroup(visibleGroups);
		}
	}
}

// 0x0024DC5C
void World::setActorCollisionStateDirty(int id)
{
	collisionDirty[id] = true;
}

// 0x0021A824: the fixed time step, used by the effects (distortion, speed blur, torpedo trails,
// metaballs, object fades, fish tank, credits).
f32 World::getDeltaTimeSeconds()
{
	return 1.0f / 30;
}

// 0x002435FC
f32 World::getGameTimeSeconds()
{
	return g_worldTime;
}

// 0x002E5620
void World::resetGameTime()
{
	g_worldTime = 0;
}

// 0x002E5638
void World::suspendCaching()
{
	recordingSuspended = true;
}

// 0x002E5D4C: -1 outside a replay.
int World::getReplayFramesRemaining()
{
	return replaying ? replayFramesRemaining : -1;
}

// 0x002E6DB4 / 0x002E6EF4
int World::getLevel() { return level; }
void World::setLevel(int level) { this->level = level; }

// 0x002E5D70: worldLoad(name, mapMask): loads romfs:/worlds/<name>.bxml.
void World::load(const char *name, u32 mapMask)
{
	char path[0x80] = "";
	strncat(path, "worlds/", sizeof(path));
	strncat(path, name, sizeof(path));
	strncat(path, ".bxml", sizeof(path));
	// DEBUG_LOG("World: load %s\n", path);   (patched out)
	BXML xml;
	xml.load(path, 0, 0x3C);
	if (BXML::Node *world = xml.findNode("world")) {
		readXML(world, mapMask);
	}
}

// 0x002E5E6C: the level format (see docs/formats.md). Three passes over the children of <world>:
// the includes first, then actors and resources, then lights and fog. A child with a "map_mask"
// attribute is only read when it shares a bit with mapMask (or when the mask is 0).
void World::readXML(BXML::Node *node, u32 mapMask)
{
	for (int i = 1; i < node->attributeCount; i++) {
		if (strcmp(node->getAttribute(i)->name, "no_idle") == 0) {
			noIdle = true;
		}
	}

	auto selected = [mapMask](BXML::Node *child) {
		BXML::Attribute *mask = child->findAttribute("map_mask");
		u32 bits = mask ? mask->asInt() : 0;
		return bits == 0 || (bits & mapMask) != 0;
	};

	// <include file="..."/>: another world, read first (recursively).
	for (BXML::Node *child = node->firstChild; child; child = child->next) {
		if (selected(child) && strcmp(child->getName(), "include") == 0) {
			char path[0x80];
			strncpy(path, child->findAttribute("file")->string(), sizeof(path));
			strcat(path, ".bxml");
			BXML xml;
			xml.load(path, 0);
			if (BXML::Node *world = xml.findNode("world")) {
				readXML(world, mapMask);
			}
		}
	}

	for (BXML::Node *child = node->firstChild; child; child = child->next) {
		if (!selected(child)) {
			continue;
		}
		const char *tag = child->getName();
		if (strcmp(tag, "actor") == 0) {
			// The node's attributes become the actor's properties (script, model, ...).
			Actor *actor = newActor();   // inlined
			actor->readProperties(child, NULL);
			// level="1 4": the actor only exists in those levels (World::setLevel).
			BXML::DynamicAttribute levels("level");
			if (actor->getAttribute(&levels)) {
				bool found = false;
				for (int k = 0; k < levels.count; k++) {
					found = found || levels.ints[k] == level;
				}
				levels.clearData();
				if (!found && actor->active) {
					actor->kill();
				}
			}
		} else if (strcmp(tag, "dust") == 0) {
			// <dust color min_alpha max_alpha [min_size max_size]/>: particles floating in the water
			Dust::setup(child->colour("color"), child->real("min_alpha"), child->real("max_alpha"),
			            child->realOr("min_size"), child->realOr("max_size"));
		} else if (strcmp(tag, "instance") == 0) {
			// <instance model position radius count rand_seed max_angle/>: scattered copies of a model
			InstanceSys::addGroup(child->integer("count"), child->string("model"), child->integer("rand_seed"),
			                      child->vector("position"), child->real("radius"), child->real("max_angle"));
		} else if (strcmp(tag, "model") == 0) {
			// <model file [mem]/>: model set loaded in advance
			if (!ModelSet::findStock(child->string("file"), 0)) {
				ModelSet *set = new ModelSet(child->string("file"), NULL, NULL);
				set->setActive(false);
			}
		} else if (strcmp(tag, "particle") == 0) {
			// <particle file/>: particle effect loaded in advance
			ParticleManager::loadModel(child->string("file"), 0);
		}
	}

	for (BXML::Node *child = node->firstChild; child; child = child->next) {
		if (!selected(child)) {
			continue;
		}
		const char *tag = child->getName();
		if (strcmp(tag, "light") == 0) {
			// <light [type="point" position] | [direction] diffuse ambient specular env name/>
			bool point = child->findAttribute("type") && strcmp(child->string("type"), "point") == 0;
			VEC3 where = point ? child->vector("position") : child->vector("direction");
			u32 diffuse = child->findAttribute("diffuse") ? child->colour("diffuse") : 0xFFFFFFFF;
			u32 ambient = child->findAttribute("ambient") ? child->colour("ambient") : 0xFF323232;
			u32 specular = child->findAttribute("specular") ? child->colour("specular") : 0xFFFFFFFF;
			int env = child->findAttribute("env") ? child->integer("env") : -1;
			const char *name = child->findAttribute("name") ? child->string("name") : "";
			for (int r = 0; r < Renderer::getNumRenderers(); r++) {
				Renderer *renderer = Renderer::getRenderer(r);
				if (!renderer->isActive() || !renderer->scene) {
					continue;
				}
				int light = point ? renderer->scene->addPointLight(name, where, diffuse, ambient, specular)
				                  : renderer->scene->addDirLight(name, where, diffuse, ambient, specular);
				if (env >= 0) {
					renderer->scene->addEnvLight(light, env);
				}
			}
		} else if (strcmp(tag, "fog") == 0) {
			// <fog color density min_depth max_depth [index] [curve] [level]/>
			int index = child->findAttribute("index") ? child->integer("index") : 0;
			u8 curve = 1;   // linear
			if (BXML::Attribute *c = child->findAttribute("curve")) {
				curve = strcmp(c->string(), "none") == 0 ? 0
				      : strcmp(c->string(), "exponent") == 0 ? 2
				      : strcmp(c->string(), "exponent_square") == 0 ? 3 : 1;
			}
			// (density, min_depth, max_depth are read here and passed in VFP registers)
			BXML::Attribute *levels = child->findAttribute("level");
			if (levels && !levels->contains(level)) {
				continue;
			}
			for (int r = 0; r < Renderer::getNumRenderers(); r++) {
				Renderer *renderer = Renderer::getRenderer(r);
				if (renderer->isActive() && renderer->scene) {
					renderer->scene->addFog(index, child->colour("color"), curve);
				}
			}
		}
	}
}

// 0x00319690: static initialiser of world.o.
static void __sti___9_world_cpp()
{
	s_unknownB8 = -1;   // 0x0038E2B8..0x0038E2C4, meaning unknown
	s_unknownBC = -1;
	s_unknownC0 = 0;
	s_unknownC4 = 0;
}
