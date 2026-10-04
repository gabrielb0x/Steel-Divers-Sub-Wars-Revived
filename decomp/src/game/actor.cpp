// source/game/actor.cpp (actor.o): the actors, objects of the world driven by Pawn scripts.
//
// Reconstructed by hand from decomp/raw/source/game/actor.cpp (and world.cpp, where armlink put
// the constructor) and the disassembly; layouts in ghidra/types.h. Not compilable on its own.
// This file covers the life cycle of an actor; the attribute (property) functions, matrices and
// the *Sim accessors are still to be cleaned.
//
// An actor is a slot of the World's pool. Its properties come from a BXML node (a level's
// <actor> element, or a properties file bxml/<name>.bxml) and are kept as dynamic attributes; the
// "script" property starts a Pawn script in the actor's own loader (ActorData::scriptLoader).
// Besides running as a coroutine like every script (AMXLoader::runAll), the script is called by
// the engine through optional public functions: @update, @visibleUpdate / @notVisibleUpdate,
// @eventCollide, @replayEnter / @replayUpdate / @replayExit and @pausedUpdate. When the script
// ends, the actor dies, unless a "stasis" script is waiting to replace it.
//
// Positions exist twice: the simulated state (positionPtr, *Sim functions) and the drawn state
// (+0x4C), copied when the matrices are updated (World::postScriptUpdate).

// 0x0010CC20 (in world.o): constructor of each pool slot (World::init builds 256 of them).
Actor::Actor()
{
	id = 0;
	data = new ActorData;      // 0x1260 bytes
	data->lastReadProperties[0] = '\0';
	data->name[0] = '\0';
	data->stasisScript[0] = '\0';
	new (&data->scriptLoader) ScriptAMXLoader();
	new (data->collResults) CollResult[8];
	data->attributeCount = 0;
	data->unknown104 = 0;
	for (int i = 0; i < 64; i++) {
		data->attributes[i] = NULL;
	}
	init();
}

// 0x0012463C: (re)initialises a slot when it is handed out (World::newActor).
void Actor::init()
{
	setPosition(VEC3(0, 0, 0));     // each of these sets matrixDirty only on change
	setScale(VEC3(1, 1, 1));
	setRotation(VEC3(0, 0, 0));
	previousRotation = rotation;
	matrix = MTX34::Identity();     // function-local static, guarded
	strncpy(data->name, "Actor", sizeof(data->name));
	data->stasisScript[0] = '\0';
	if (active != 1) {
		g_world->setActorCollisionStateDirty(id);
	}
	active = true;
	onCollide = -1;
	collShapeCount = 0;
	onNotVisibleUpdate = -1;
	unknown05 = true;
	for (u32 i = 0; i < data->attributeCount; i++) {
		data->attributes[i]->clear();
	}
	data->unknown104 = 0;
	model = NULL;
	script = NULL;
	typeMask = 0;
	idleDistanceSq = 15000.0f * 15000.0f;
	idleDistance = 15000.0f;
	idle = false;
	onMap = 0;
	isStatic = false;
	recorded = false;
	customFlags = 0;
	customValues[0] = customValues[1] = customValues[2] = 0;
	// ... (the rest of the 916 bytes resets the remaining fields; not cleaned yet)
}

// 0x0010CBD8
void Actor::setActive(bool active)
{
	if (this->active != active) {
		g_world->setActorCollisionStateDirty(id);
		if (!active) {
			g_world->invalidateActor(id);
		}
	}
	this->active = active;
}

// 0x002432A4: "script" property: (re)starts a script in the actor's loader.
void Actor::setScript(const char *name)
{
	if (script) {
		script->cleanup();
	}
	script = &data->scriptLoader;
	script->init();
	script->load(name, 0);
	script->setUserObj(true, this);
	onCollide = script->findPublic("@eventCollide");
	if (onCollide == -1) {
		onCollide = script->findPublic("@eventCollideTag");
	}
	onUpdate = script->findPublic("@update");
	onVisibleUpdate = script->findPublic("@visibleUpdate");
	onNotVisibleUpdate = script->findPublic("@notVisibleUpdate");
	onReplayEnter = script->findPublic("@replayEnter");
	onReplayExit = script->findPublic("@replayExit");
	onReplayUpdate = script->findPublic("@replayUpdate");
	onPausedUpdate = script->findPublic("@pausedUpdate");
}

// 0x002E24AC: script to start when the current one ends (instead of the actor dying).
void Actor::setStasisScript(const char *name)
{
	if (name) {
		strncpy(data->stasisScript, name, sizeof(data->stasisScript));
	} else {
		data->stasisScript[0] = '\0';
	}
}

// 0x0010C7FC: once per frame (World::update) unless idle or the game is paused.
void Actor::update()
{
	if (script) {
		if (script->isFinished() && data->stasisScript[0]) {
			setScript(data->stasisScript);
			data->stasisScript[0] = '\0';
		}
		procCollisions();       // calls onCollide for the collisions of the last frame
	}
	updateMatrix();
	if (layout) {
		Layout::animate(layout);
	}
	modelOnScreen = model && model->onScreen;    // +0x3C, ModelSet +0xA1
	bool replay = onReplayUpdate != -1 && g_world->replaying;

	if (!script) {
		// nothing to call
	} else if (!isStatic && script->isFinished() && !data->stasisScript[0]) {
		// The script is over: the actor dies (kill() inlined, plus a zero scale to hide it).
		if (scale != VEC3(0, 0, 0)) {
			scale = VEC3(0, 0, 0);
			matrixDirty = true;
		}
		removeModel();
		script->cleanup();
		script = NULL;
		setCacheable(false);
		if (active) {
			g_world->setActorCollisionStateDirty(id);
			g_world->invalidateActor(id);
		}
		active = false;
		for (int i = 0; i < collShapeCount; i++) {
			collShapes[i]->enabled = false;    // CollShape +0x67
		}
	} else if (!script->isFinished()
			&& (onUpdate != -1 || onVisibleUpdate != -1 || onNotVisibleUpdate != -1 || replay || callOnce != -1)) {
		AMXState state;
		script->freezeState(&state);
		if (callOnce != -1) {
			script->callFunction(callOnce);
			callOnce = -1;
		}
		if (replay) {
			script->callFunction(onReplayUpdate);
		}
		if (onUpdate != -1) {
			script->callFunction(onUpdate);
		}
		if (model) {
			int function = model->onScreen ? onVisibleUpdate : onNotVisibleUpdate;
			if (function != -1) {
				script->callFunction(function);
			}
			if (model) {
				model->onScreen = false;
			}
		}
		if (script) {
			script->thawState(&state);
		}
	}

	if (unknown14 != 0) {
		unknown14--;
	}
}

// 0x0010C790: instead of update() while the game is paused.
void Actor::updatePaused()
{
	if (layout) {
		Layout::animate(layout);
	}
	if (script && onPausedUpdate != -1) {
		AMXState state;
		script->freezeState(&state);
		script->callFunction(onPausedUpdate);
		script->thawState(&state);
	}
}

// 0x0010CB44: an actor whose script runs is idle (not updated) when, seen from above, it is
// farther from the camera than its idle distance (15000 by default, 0 = never idle).
bool Actor::calcIdle(const VEC3 *cameraPos)
{
	bool nowIdle = false;
	if (script && idleDistanceSq > 0) {
		f32 dx = cameraPos->x - position[0];
		f32 dz = cameraPos->z - position[2];
		nowIdle = dx * dx + dz * dz > idleDistanceSq;
	}
	if (idle != nowIdle) {
		idle = nowIdle;
		setVisible();
		g_world->setActorCollisionStateDirty(id);
	}
	return idle;
}

// 0x0010C6F4: frustum test of the model when it asks for one (ModelSet +0xAC).
void Actor::calcVisible()
{
	if (!model) {
		return;
	}
	bool inView = true;
	if (model->cullable) {
		Renderer *renderer = Renderer::getRenderer(this->renderer);
		VEC3 relative = VEC3(position[0], position[1], position[2]) - renderer->cameraPos;   // +0xF4
		inView = renderer->frustum.contains(relative, model->radius);       // +0x124, ModelSet +0xA8
	}
	if (inFrustum != inView) {     // +0x3D
		inFrustum = inView;
		setVisible();
	}
}

// 0x001E0B28: actorKill().
void Actor::kill()
{
	removeModel();
	if (script) {
		script->cleanup();
		script = NULL;
	}
	setCacheable(false);
	if (active) {
		g_world->setActorCollisionStateDirty(id);
		g_world->invalidateActor(id);
	}
	active = false;
	for (int i = 0; i < collShapeCount; i++) {
		collShapes[i]->enabled = false;
	}
}

// 0x0023B88C: actorReadProperties("name"): properties file bxml/<name>.bxml.
//   <mount_dlc_arc content_index="n"/>   the add-on content archive to mount while reading
//                                       (models of the premium submarines)
//   <actor attribute="value" ...>       the actor's properties
//     <collshape type="sphere" .../>    up to 2 collision shapes (CollShape::create)
//   </actor>
// Returns false if the add-on content is not available.
bool Actor::readProperties(const char *name)
{
	char path[0x80] = "";
	strncat(path, "bxml/", sizeof(path));
	strncat(path, name, sizeof(path));
	strncat(path, ".bxml", sizeof(path));
	BXML xml;
	xml.load(path, 0);

	bool mounted = false, available = true;
	if (BXML::Node *dlc = xml.findNode("mount_dlc_arc")) {
		int content = dlc->getAttribute(1)->asInt();    // "content_index"
		getNsubShop()->updateCondition();
		if (getNsubShop()->checkCondition(content)) {
			mounted = available = getNsubShop()->mountContentArchive(content);
		} else {
			available = false;
		}
	}
	if (BXML::Node *node = xml.findNode("actor")) {
		for (int i = 1; i < node->attributeCount; i++) {
			setAttribute(node->getAttribute(i));       // vtable slot 1
		}
		for (BXML::Node *child = node->firstChild; child; child = child->next) {
			if (strcmp(child->getName(), "collshape") == 0) {
				collShapes[collShapeCount++] = CollShape::create(child);
			}
		}
		strncpy(data->lastReadProperties, name ? name : "", sizeof(data->lastReadProperties));
	}
	if (mounted) {
		getNsubShop()->unmountContentArchive();
	}
	return available;
}

// 0x002E3048
void Actor::getLastReadProperties(char *dest)
{
	strncpy(dest, data->lastReadProperties, 0x80);
}

// 0x0023F23C: name of the actor's script (empty without one).
void Actor::getScript(char *dest)
{
	if (script) {
		script->getName(dest);
	}
}

// 0x002E249C
void Actor::setIdleDistance(f32 distance)
{
	idleDistance = distance;
	idleDistanceSq = distance * distance;
}

// 0x002E1D68 / 0x002E1E4C: actorGetCustomFlag / actorGetCustomValue.
u32 Actor::getCustomFlag(u32 bit) { return customFlags & (1 << bit); }
f32 Actor::getCustomValue(int index) { return customValues[index] * (1.0f / 255); }   // 0..1 in a byte

// 0x00242E00 / 0x00116914: drawn state; the matrix is rebuilt when something changed.
void Actor::setPosition(const VEC3 &p)
{
	if (position != p) {
		position = p;
		matrixDirty = true;
	}
}

void Actor::setRotation(const VEC3 &r)
{
	if (rotation != r) {
		rotation = r;
		matrixDirty = true;
	}
}
