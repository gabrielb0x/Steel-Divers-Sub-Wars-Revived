// source/game/actor.cpp (actor.o): the actors, objects of the world driven by Pawn scripts.
//
// Reconstructed by hand from decomp/raw/source/game/actor.cpp (and world.cpp, where armlink put
// the constructor) and the disassembly; layouts in ghidra/types.h. Not compilable on its own.
// Not here: Actor::loadEnvironment (0x001E1934), a thunk into Scene::loadEnvironment (scene.cpp).
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
	data->freeAttribute = 0;
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
	groupVisible = true;
	for (u32 i = 0; i < data->attributeCount; i++) {
		data->attributes[i]->clear();
	}
	data->freeAttribute = 0;
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

	if (replayFramesLeft != 0) {
		replayFramesLeft--;
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

// ---- attributes ------------------------------------------------------------------------------------------
// An actor's properties (a level's <actor .../>, bxml/<name>.bxml, actorSetAttribute*) go through
// setAttribute (vtable +0x04). The names the engine knows act at once; any other is kept in the actor's own
// table (up to 64 DynamicAttributes of 0x78 bytes, sorted by name hash, free ones of type 100 at the end) for
// the scripts to read back (actorGetAttribute*). Names are first told apart by their first 4 characters read
// as an integer, then compared whole (except "uid", "yaw" and "dir", which fit in 4 bytes).
//
// The angles "pitch", "yaw" and "roll" are given in degrees and kept in radians; "dir" is a quarter turn
// count (yaw = dir * 90°). Read back (getAttribute), they stay in radians; "rotation" is radians both ways.

// 0x002E1BF8
bool Actor::setAttribute(const BXML::Attribute *a, bool keepScript)
{
	bool done = setAttributeString(a, keepScript) || setAttributeVector(a) || setAttributeFloat(a) || setAttributeInt(a);
	if (!done) {
		if (strcmp(a->name, "load_env") == 0) {
			// The scene's fog and lights from the model (Scene::loadEnvironment); before the model is set or
			// while a level is loading, setModel does it later.
			if (a->boolean()) {
				if (model == nullptr || g_world->getLevel() != nullptr)
					loadEnvPending = true;
				else
					Renderer::getRenderer(renderer)->scene->loadEnvironment(model);
			}
		} else {
			done = saveDefAttribute(BXML::DynamicAttribute(*a));   // full: a log (line lost), and false
		}
	}
	matrixDirty = true;
	return done;
}

// 0x001DAF54: the same into the table only.
bool Actor::setAttributeCommon(const BXML::Attribute *a)
{
	return saveDefAttribute(BXML::DynamicAttribute(*a));
}

// 0x002E29F4: script, name, model*, layout*, properties.
bool Actor::setAttributeString(const BXML::Attribute *a, bool keepScript)
{
	const char *name = a->name, *value = a->string();
	if (strcmp(name, "script") == 0) {
		if (keepScript)                     // a flag of setAttribute's caller: "script" only goes to the table
			return false;
		if (value != nullptr) {
			setScript(value);
			script->uid = id;               // the script's UID is the actor's id
		}
		return true;
	}
	if (strcmp(name, "name") == 0) {
		strncpy(data->name, value ? value : "", 0x20);
		return true;
	}
	// The model: in the device memory, or "fcram" (the main memory), and "mutable" (an own copy, whose
	// materials the script may change); "_dlc" reads it from the add-on content's archive when mounted.
	if (strcmp(name, "model") == 0) { setModel(value, false, false); return true; }
	if (strcmp(name, "model_fcram") == 0) { setModel(value, true, false); return true; }
	if (strcmp(name, "model_mutable") == 0) { setModel(value, true, true); return true; }
	if (strcmp(name, "model_mutable_dlc") == 0) {
		if (getNsubShop()->contentArchiveMounted) {
			Resource::setArchiveName(NsubShop::getContentArchiveName());
			setModel(value, true, true);
			Resource::setArchiveName(nullptr);
		}
		return true;
	}
	if (strcmp(name, "properties") == 0) {
		readProperties(value);
		return true;
	}
	// A 2D layout instead of a model: "layout" / "dynamic_layout" in the main memory, "layout_vram" /
	// "dynamic_layout_vram" in VRAM (the two names of each pair do the same).
	bool vram;
	if (strcmp(name, "layout") == 0 || strcmp(name, "dynamic_layout") == 0)
		vram = false;
	else if (strcmp(name, "layout_vram") == 0 || strcmp(name, "dynamic_layout_vram") == 0)
		vram = true;
	else
		return false;
	Renderer *r = Renderer::getRenderer(renderer);
	layout = new Layout();
	layout->load(value, r->layoutHeap, true, !vram);    // Renderer +0x114C
	r->addDrawable(layout, 0, 0);
	setVisible();
	return true;
}

// 0x002E2E58: rotation (radians, simulated state), position, velocity, torque.
bool Actor::setAttributeVector(const BXML::Attribute *a)
{
	if (strcmp(a->name, "rotation") == 0) {
		rotationSim() = a->vec3();
		matrixDirty = true;
	} else if (strcmp(a->name, "position") == 0) {
		VEC3 p = a->vec3();
		if (replayed)
			data->positionSim = p;
		else
			setPosition(p);
	} else if (strcmp(a->name, "velocity") == 0) {
		velocity = a->vec3();
		moving = velocity != VEC3(0, 0, 0);
	} else if (strcmp(a->name, "torque") == 0) {
		torque = a->vec3();
	} else {
		return false;
	}
	return true;
}

// 0x002E26F0: idle_distance, dir, yaw, pitch, roll, scale (the same on the 3 axes). The angles go to the
// drawn rotation, not the simulated one.
bool Actor::setAttributeFloat(const BXML::Attribute *a)
{
	const f32 DEG = (1 / 180.0f) * 3.1415927f;
	const char *name = a->name;
	if (strcmp(name, "idle_distance") == 0)
		setIdleDistance(a->number());
	else if (strcmp(name, "dir") == 0)
		rotation[1] = a->number() * 90 * DEG;
	else if (strcmp(name, "yaw") == 0)
		rotation[1] = a->number() * DEG;
	else if (strcmp(name, "pitch") == 0)
		rotation[0] = a->number() * DEG;
	else if (strcmp(name, "roll") == 0)
		rotation[2] = a->number() * DEG;
	else if (strcmp(name, "scale") == 0) {
		f32 k = a->number();
		if (scale != VEC3(k, k, k)) {
			scale = VEC3(k, k, k);
			matrixDirty = true;
		}
	} else
		return false;
	return true;
}

// 0x002E2188: collision_type, anim_auto, priority (read, unused), group, map_type, cacheable, visible.
bool Actor::setAttributeInt(const BXML::Attribute *a)
{
	const char *name = a->name;
	if (strcmp(name, "collision_type") == 0)
		setCollisionType(a->integer());
	else if (strcmp(name, "anim_auto") == 0) {
		animAuto = a->integer() != 0;
		if (animAuto && model != nullptr)
			for (int i = 0; i < model->animCount; i++) {
				model->getAnimNum(i)->reset();      // vtable +0x18, then +0x10: from the start, playing
				model->getAnimNum(i)->play();
			}
	} else if (strcmp(name, "priority") == 0)
		a->integer();
	else if (strcmp(name, "group") == 0)
		groups = a->integer();
	else if (strcmp(name, "map_type") == 0)
		onMap = a->integer();
	else if (strcmp(name, "cacheable") == 0)
		setCacheable(a->integer() != 0);
	else if (strcmp(name, "visible") == 0)
		setVisibleSim(a->integer() != 0);
	else
		return false;
	return true;
}

// 0x002E1858: visible, rotation, uid (the script's), yaw, pitch, roll, name, position, scale, velocity,
// torque from the actor's state (simulated where it has one); any other from the table. False if unknown.
bool Actor::getAttribute(BXML::DynamicAttribute *a)
{
	const char *name = a->name;
	if (strcmp(name, "visible") == 0) a->setInt(((const ActorState *)positionPtr)->visible);
	else if (strcmp(name, "rotation") == 0) a->setVector3(rotationSim());
	else if (strcmp(name, "uid") == 0) a->setInt(script->uid);
	else if (strcmp(name, "yaw") == 0) a->setFloat(rotationSim()[1]);
	else if (strcmp(name, "pitch") == 0) a->setFloat(rotationSim()[0]);
	else if (strcmp(name, "roll") == 0) a->setFloat(rotationSim()[2]);
	else if (strcmp(name, "name") == 0) a->setString(data->name);
	else if (strcmp(name, "position") == 0) a->setVector3(positionPtr);
	else if (strcmp(name, "scale") == 0) a->setVector3(scale);
	else if (strcmp(name, "velocity") == 0) a->setVector3(velocity);
	else if (strcmp(name, "torque") == 0) a->setVector3(torque);
	else if (const BXML::DynamicAttribute *saved = findDefAttribute(a->hash, a->name)) *a = *saved;
	else return false;
	return true;
}

// 0x002E24E0: a binary search by name hash among the used attributes. The names are then compared, but the
// result is ignored: two names of the same CRC-32 would share one attribute.
const BXML::DynamicAttribute *Actor::findDefAttribute(u32 hash, const char *name)
{
	if (data->attributeCount == 0)
		return nullptr;
	int lo = 0, hi = std::min(data->freeAttribute, data->attributeCount - 1), found = -1;
	while (lo <= hi && found == -1) {
		int mid = (lo + hi) / 2;
		u32 h = data->attributes[mid]->hash;
		if (h > hash) hi = mid - 1;
		if (h < hash) lo = mid + 1;
		if (h == hash) found = mid;
	}
	if (found == -1)
		return nullptr;
	strcmp(data->attributes[found]->name, name);
	return data->attributes[found];
}

// 0x002E2580: replaces the attribute of that name, else fills the first free one, else allocates one (64
// at most); the table is then sorted again (shiftAttribute).
bool Actor::saveDefAttribute(const BXML::DynamicAttribute &a)
{
	if (BXML::DynamicAttribute *same = (BXML::DynamicAttribute *)findDefAttribute(a.hash, a.name)) {
		*same = a;
		return true;
	}
	for (u32 i = 0; i < data->attributeCount; i++)
		if (data->attributes[i]->type() == 100) {
			*data->attributes[i] = a;
			shiftAttribute(i);
			return true;
		}
	if (data->attributeCount >= 64)
		return false;
	data->attributes[data->attributeCount] = new BXML::DynamicAttribute();
	*data->attributes[data->attributeCount] = a;
	shiftAttribute(data->attributeCount++);
	return true;
}

// 0x002E1FD8: moves attribute i to its place: a freed one (type 100) to the end, a new one down or up
// among the used ones by hash; then freeAttribute = the first free one (or the count).
void Actor::shiftAttribute(u32 i)
{
	BXML::DynamicAttribute **t = (BXML::DynamicAttribute **)data->attributes;
	u32 n = data->attributeCount;
	if (t[i]->type() == 100) {
		for (; i < n - 1; i++)
			std::swap(t[i], t[i + 1]);
	} else {
		u32 hash = t[i]->hash;
		for (u32 k = i; k < n - 1 && t[k + 1]->hash < hash && t[k + 1]->type() != 100; k++)
			std::swap(t[k], t[k + 1]);
		for (; (int)i > 0 && t[i - 1]->hash > hash; i--)
			std::swap(t[i], t[i - 1]);
	}
	data->freeAttribute = n;
	for (u32 k = 0; k < n; k++)
		if (t[k]->type() == 100) {
			data->freeAttribute = k;
			break;
		}
}

// 0x002E1E6C: a node's attributes (the first, the node's own kind, skipped) and its <collshape> children.
void Actor::readProperties(const BXML::Node *node)
{
	for (int i = 1; i < node->attributeCount; i++)
		setAttribute(node->getAttribute(i));
	for (const BXML::Node *child = node->getChild(); child != nullptr; child = child->getSibling())
		if (strcmp(child->getName(), "collshape") == 0)
			collShapes[collShapeCount++] = CollShape::create(child);   // no check against the 2 slots
}

// ---- collisions, types -----------------------------------------------------------------------------------

// 0x002E2670 / 0x002E2924: actorSetCollisionType / actorSetCollisionCheck; a change rebuilds the actor's
// collision pairs (collisionscene.cpp).
void Actor::setCollisionType(u32 type)
{
	if (typeMask != type)
		g_world->setActorCollisionStateDirty(id);
	typeMask = type;
}

void Actor::setCollisionCheck(u32 mask)
{
	if (collisionMask != mask)
		g_world->setActorCollisionStateDirty(id);
	collisionMask = mask;
}

// 0x00116A60: each collision of the frame to the script's @eventCollide(other, point[3], normal[3],
// velocity[3], depth, part) (pushed in reverse: part first), the renderers set to the script's mask while it
// runs; then the list is emptied. Kept when the script has no @eventCollide.
void Actor::procCollisions()
{
	if (script == nullptr || onCollide < 0 || collResultCount == 0)
		return;
	for (int i = 0; i < collResultCount; i++) {
		CollResult *r = &((CollResult *)data->collResults)[i];
		Renderer::setActiveMask(script->rendererMask);         // AMXLoader +0x224
		AMXCall call;
		script->beginCall(&call);                               // vtable +0x14
		script->push(r->part);                                  // +0x18
		script->push(amx_ftoc(r->depth));
		script->pushArray(r->otherVelocity, 3);                 // +0x1C
		script->pushArray(r->normal, 3);
		script->pushArray(r->point, 3);
		script->push(r->actorB->id);
		script->exec(onCollide);                                // +0x24
		script->endCall(&call);                                 // +0x28
	}
	collResultCount = 0;
}

// ---- model, layout, visibility ---------------------------------------------------------------------------

// 0x001E1720: the model of that name, unless it is already the actor's. A shared model comes from the
// stock (ModelSet::findStock), a mutable one is the actor's own (0xB4 bytes). It starts hidden, its
// bounding box far away (10000) until the next update, then is shown by setVisible.
void Actor::setModel(const char *name, bool fcram, bool mutableCopy)
{
	if (model != nullptr && strcmp(model->name, name) == 0)       // ModelSet +0x20
		return;
	removeModel();
	model = ModelSet::findStock(name, mutableCopy ? this : nullptr);
	if (model == nullptr)
		model = new ModelSet(name, fcram, mutableCopy);
	model->setActive(true);
	model->setVisible(false);
	if (mutableCopy)
		model->owner = this;                                    // +0xB0
	nw::gfx::Model *m = model->root;                            // +0x0C
	m->boundsMax = VEC3(10000, 10000, 10000);                   // +0x58, +0x68, +0x78
	m->flags |= 0x800;                                          // the world matrix changed
	setVisible();
	if (animAuto)
		for (int i = 0; i < model->animCount; i++) {
			model->getAnimNum(i)->reset();
			model->getAnimNum(i)->play();
		}
	if (loadEnvPending && g_world->getLevel() == nullptr) {
		Renderer::getRenderer(renderer)->scene->loadEnvironment(model);
		loadEnvPending = false;
	}
	matrixDirty = true;
}

// 0x002431C4: the model out of every renderer's scene, the layout out of every renderer (and deleted).
void Actor::removeModel()
{
	if (model != nullptr) {
		for (int i = 0; i < Renderer::getNumRenderers(); i++)
			if (Scene *scene = Renderer::getRenderer(i)->scene)
				scene->removeModelSet(model);
		model->setActive(false);
		model->setVisible(false);
		model = nullptr;
		inScene = false;
	}
	if (layout != nullptr) {
		for (int i = 0; i < Renderer::getNumRenderers(); i++)
			Renderer::getRenderer(i)->removeDrawable(layout);
		delete layout;
		layout = nullptr;
	}
}

// 0x002E308C: actorSetLayout(name, layer, vram...).
void Actor::setLayout(const char *name, int layer, bool mainMemory)
{
	Renderer *r = Renderer::getRenderer(renderer);
	layout = new Layout();
	layout->load(name, r->layoutHeap, true, mainMemory);
	r->addDrawable(layout, layer, 0);
	setVisible();
}

// 0x00243478 setVisible(v) stores it, then runs into 0x00243480 setVisible(): the model is drawn when one
// of its groups is shown, it is visible and in the frustum; it stays in the scene (but hidden) while the
// ModelSet asks for it (+0xAD). A layout's root pane is shown when the group and `visible` allow it.
void Actor::setVisible(bool v)
{
	visible = v;
	setVisible();
}

void Actor::setVisible()
{
	if (model != nullptr) {
		bool drawn = groupVisible && visible && inFrustum;
		bool wanted = drawn || model->keepInScene;
		model->setVisible(drawn);
		if (inScene != wanted) {
			Scene *scene = Renderer::getRenderer(renderer)->scene;     // Renderer +0x113C
			if (wanted)
				scene->addModelSet(model);
			else
				scene->removeModelSet(model);
			inScene = wanted;
		}
	}
	if (layout != nullptr)
		layout->getRootPane()->setVisible(groupVisible && visible);
}

// 0x002E24CC: World::showGroup's mask against the actor's groups.
void Actor::changeVisOnGroup(u32 shown)
{
	groupVisible = (shown & groups) != 0;
	setVisible();
}

// ---- matrices --------------------------------------------------------------------------------------------

// 0x0011B2E4: the rotation matrix of Euler angles applied Z, then X, then Y (the translation column is left
// alone).
void TestMatrixRotZXY(MTX34 *m, const VEC3 &r)
{
	f32 sx = sinf(r.x), cx = cosf(r.x), sy = sinf(r.y), cy = cosf(r.y), sz = sinf(r.z), cz = cosf(r.z);
	m->m[0][0] = cy * cz + sy * sz * sx;  m->m[0][1] = sy * cz * sx - cy * sz;  m->m[0][2] = cx * sy;
	m->m[1][0] = cx * sz;                 m->m[1][1] = cx * cz;                 m->m[1][2] = -sx;
	m->m[2][0] = cy * sz * sx - sy * cz;  m->m[2][1] = sy * sz + cy * cz * sx;  m->m[2][2] = cx * cy;
}

// 0x0024DC88: the drawn matrix from the drawn position and rotation (the sines only when the rotation
// changed), copied into the model's world matrix; a layout gets its root pane's translation and rotation
// instead. A replayed actor also rebuilds its replay matrix.
void Actor::updateMatrix()
{
	if (matrixDirty) {
		if (layout != nullptr) {
			Pane *root = layout->getRootPane();
			root->translate = VEC3(position);               // +0x28
			root->flags &= ~0x30;                           // +0xB7: the matrices must be rebuilt
			root = layout->getRootPane();
			root->rotate = VEC3(rotation);                  // +0x34
			root->flags &= ~0x30;
		} else if (model != nullptr) {
			if (VEC3(rotation) != VEC3(previousRotation)) {
				TestMatrixRotZXY((MTX34 *)matrix, VEC3(rotation));
				previousRotation = rotation;
			}
			matrix[3] = position[0];
			matrix[7] = position[1];
			matrix[11] = position[2];
			inverseDirty = true;
			nn::math::MTX34Copy(&model->root->worldMatrix, (MTX34 *)matrix);   // +0x4C
			model->root->flags |= 0x800;
		}
		matrixDirty = false;
	}
	if (replayed && model != nullptr) {
		TestMatrixRotZXY((MTX34 *)data->matrixSim, VEC3(data->rotationSim));
		data->matrixSim[3] = data->positionSim[0];
		data->matrixSim[7] = data->positionSim[1];
		data->matrixSim[11] = data->positionSim[2];
	}
}

// 0x0021BA68 / 0x001DAAB8 / 0x0021BA84: the matrix the simulation sees (the replay's while replayed) and the
// inverses, rebuilt when dirty. The replayed inverse is rebuilt only when the drawn one is dirty, and clears
// that flag: the two share it.
const MTX34 *Actor::getMatrixSim() { return replayed ? (MTX34 *)data->matrixSim : (MTX34 *)matrix; }

const MTX34 *Actor::getInverseMatrix()
{
	if (inverseDirty) {
		MTX34Inverse((MTX34 *)inverseMatrix, (MTX34 *)matrix);     // 0x0023CCB0
		inverseDirty = false;
	}
	return (MTX34 *)inverseMatrix;
}

const MTX34 *Actor::getInverseMatrixSim()
{
	if (!replayed)
		return getInverseMatrix();
	if (inverseDirty) {
		MTX34Inverse((MTX34 *)data->inverseMatrixSim, (MTX34 *)data->matrixSim);
		inverseDirty = false;
	}
	return (MTX34 *)data->inverseMatrixSim;
}

// 0x002E3060 getAxis, 0x002E1784 getAxisSim, 0x002E29C8 getAxisWithRollSim: the same code, three names (the
// "WithRoll" one too): column `axis` of the simulation's matrix (0 right, 1 up, 2 forward).
VEC3 Actor::getAxis(int axis)
{
	const MTX34 *m = getMatrixSim();
	return VEC3(m->m[0][axis], m->m[1][axis], m->m[2][axis]);
}

// ---- the simulated state and the replay -------------------------------------------------------------------
// While the replay plays the actor back (`replayed`), positionPtr points at ActorData +0x11E0: the scripts'
// moves go there, and the drawn state (+0x4C) is the recording's.

f32 *Actor::rotationSim() { return positionPtr + 3; }       // 0x0024DC7C

// 0x002E1F3C
void Actor::setPositionSim(const VEC3 &p)
{
	if (replayed)
		data->positionSim = p;
	else
		setPosition(p);
}

void Actor::setRotationSim(const VEC3 &r) { rotationSim() = r; matrixDirty = true; }                 // 0x002E1FBC
void Actor::addPositionSim(const VEC3 &d) { VEC3(positionPtr) += d; matrixDirty = true; }           // 0x002E1D9C
void Actor::addRotationSim(const VEC3 &d) { VEC3(rotationSim()) += d; matrixDirty = true; }         // 0x002E1DDC

// 0x002E1D78
void Actor::setVisibleSim(bool v)
{
	if (replayed)
		data->visibleSim = v;
	else
		setVisible(v);
}

// 0x002E26A4: one of the 8 custom flags (actorSetCustomFlag), in the state the simulation sees.
void Actor::setCustomFlagSim(int bit, bool on)
{
	u8 &flags = replayed ? *(u8 *)&data->customSim : customFlags;
	flags = on ? flags | 1 << bit : flags & ~(1 << bit);
}

// 0x002E2958: one of the 3 custom values, 0..1 kept in a byte.
void Actor::setCustomValueSim(int index, f32 v)
{
	v = clamp(v, 0.0f, 1.0f);
	u8 *values = replayed ? (u8 *)&data->customSim + 1 : customValues;
	values[index] = VectorFloatToUnsigned(v * 255, 3);
}

// 0x002E1E20: an actor recorded (or recently) and not already played back.
bool Actor::canEnterReplay() { return (recorded || replayFramesLeft != 0) && !replayed; }

// 0x002E17B0: the replay starts: the simulated state becomes a copy of the drawn one, and @replayEnter is
// called next update.
void Actor::enterReplay()
{
	if (canEnterReplay()) {
		positionPtr = data->positionSim;
		memcpy(data->positionSim, position, 0x20);  // position, rotation, visible, custom
		replayed = true;
		inverseDirty = matrixDirty = true;
		updateMatrix();
	}
	callOnce = onReplayEnter;
}

// 0x001167F0: the replay ends: the drawn state takes the simulated one back (what the scripts did
// meanwhile), and @replayExit is called next update.
void Actor::replayEnded()
{
	if (replayed) {
		positionPtr = position;
		setPosition(VEC3(data->positionSim));
		if (VEC3(rotation) != VEC3(data->rotationSim)) {
			rotation = data->rotationSim;
			matrixDirty = true;
		}
		visible = data->visibleSim;
		setVisible();
		*(u32 *)&customFlags = data->customSim;
		inverseDirty = matrixDirty = true;
		replayed = false;
		updateMatrix();
	}
	callOnce = onReplayExit;
}

// 0x002430C0: "cacheable" (actorSetCacheable): recorded by the replay. Cleared, the actor stays in the
// recording 210 more frames (the replay's length). Set during a replay, the actor enters it at once,
// hidden.
void Actor::setCacheable(bool on)
{
	if (!on) {
		if (recorded) {
			replayFramesLeft = 210;
			recorded = false;
		}
		return;
	}
	recorded = on;
	if (g_world->replaying) {
		if (!replayed) {
			positionPtr = data->positionSim;
			memcpy(data->positionSim, position, 0x20);
			replayed = true;
			inverseDirty = matrixDirty = true;
			updateMatrix();
		}
		callOnce = onReplayEnter;
		visible = false;
		setVisible();
	}
}

// 0x00319234 __sti___9_actor_cpp: the module's statics.
