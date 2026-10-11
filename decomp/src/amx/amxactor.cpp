// source/amx/amxactor.cpp (amxactor.o): the actor natives of the scripts (table natives_Actor, registered
// by amx_ActorInit 0x00171950). Almost every one takes the actor last (0: the calling script's actor:
// AMXLoader::getActor) and does nothing (returns 0) when there is none. Panes, animations and models are
// passed as native pointers in cells (actorFindPane, actorGetAnim...).
//
// Reconstructed by hand from decomp/raw/source/amx/amxactor.cpp and the disassembly. Not compilable on its
// own. Prototypes: decomp/pawn/natives.inc. Actor fields: ghidra/types.h.

#define SELF  AMXLoader *self = AMXLoader::getCurrentLoader()
#define ACTOR(i) Actor *a = self->getActor(p[i]); if (a == nullptr) return 0
#define OUT(i) self->getAddr(p[i], 0)
static void put3(cell *out, const f32 v[3]) { memcpy(out, v, 12); }
static void name(AMXLoader *self, char *dst, cell addr) { dst[0] = 0; self->getString(dst, addr); }

// ---- identity, script, synchronisation -----------------------------------------------------------------

static cell n_actorGetID(AMX *, const cell *) { SELF; Actor *a = self->getActor(0); return a ? a->id : 0; }    // 0x0031EB6C
static cell n_actorGetByUID(AMX *, const cell *p)                                                            // 0x001DB460: the actor of a script (as a pointer)
{
	AMXLoader *s = AMXLoader::uidToAmx(p[1]);
	return s->hasActor == 1 ? (cell)s->actor : 0;
}
static cell n_actorGetUID(AMX *, const cell *p)                                                              // 0x0031F828: its script's UID, else its id
{
	SELF; ACTOR(1);
	return a->script ? a->script->getUID() : a->id;
}
static cell n_actorGetScript(AMX *, const cell *p) { SELF; char s[384]; s[0] = 0; self->getName(s); self->setString(s, p[1]); return 1; }   // 0x0031F7D4 (the caller's own)
static cell n_actorGetParent(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[1]); return a ? a->parent : -1; }   // 0x0031F264
// 0x0031DB84: actorAttachChild(child, parent): both actors are looked up; the attaching call was compiled
// out (an empty debug function): nothing happens.
static cell n_actorAttachChild(AMX *, const cell *p) { SELF; self->getActor(p[2]); self->getActor(p[1]); return 0; }

// Synchronisation (synclist.cpp): the sync id (-1), whether synced, the owner's node id, an actor by (owner, id).
static cell n_actorGetSyncID(AMX *, const cell *p) { SELF; return SyncList::actorGetID(self->getActor(p[1])); }               // 0x001DB168
static cell n_actorIsSynced(AMX *, const cell *p) { SELF; return SyncList::actorIsSynced(self->getActor(p[1])); }              // 0x002F46DC
static cell n_actorGetSyncController(AMX *, const cell *p) { SELF; return SyncList::actorGetController(self->getActor(p[1])); } // 0x002F49A0
static cell n_actorGetFromSyncID(AMX *, const cell *p) { Actor *a = SyncList::actorGetFromID(p[1], p[2]); return a ? a->id : -1; }   // 0x0031EB48

// Flags and values the replay records with the actor (customFlags, customValues).
static cell n_actorGetCustomFlag(AMX *, const cell *p) { SELF; return self->getActor(p[2])->customFlags & 1 << (p[1] & 0xFF); }   // 0x002E1D44
static cell n_actorGetCustomValue(AMX *, const cell *p) { SELF; return amx_ftoc(self->getActor(p[2])->getCustomValue(p[1] & 0xFF)); }   // 0x0031E9F0
static cell n_actorGetCacheable(AMX *, const cell *p) { SELF; ACTOR(1); return a->recorded; }          // 0x0031E9B0: recorded in the replay
static cell n_actorGetCollisionType(AMX *, const cell *p) { SELF; ACTOR(1); return a->typeMask; }      // 0x0031E9D0
static cell n_actorGetMapType(AMX *, const cell *p) { SELF; return self->getActor(p[1])->onMap; }      // 0x0031EBE8
static cell n_actorIsOnScreen(AMX *, const cell *p) { SELF; return self->getActor(p[1])->onScreen; }   // 0x0031F8E0 (+0x3C)
static cell n_actorIsVisible(AMX *, const cell *p) { SELF; return self->getActor(p[1])->simulated()->visible; }   // 0x0031F8FC (the simulated block's)

// ---- position, rotation, scale: simulated (positionPtr) and drawn (+0x4C) ------------------------------

static cell n_actorGetPosition(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->positionPtr); return 1; }        // 0x0031F2B0
static cell n_actorGetRotation(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->rotationSim()); return 1; }      // 0x0031F71C
static cell n_actorGetScale(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->scale); return 1; }                 // 0x0031F780
static cell n_actorGetVelocity(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->velocity); return 1; }           // 0x0031F864 (+0xF8)
static cell n_actorGetPitch(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotationSim()[0]); }             // 0x0031F288
static cell n_actorGetYaw(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotationSim()[1]); }               // 0x0031F8B8
static cell n_actorGetRoll(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotationSim()[2]); }              // 0x0031F6F4
static cell n_actorGetDrawPosition(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->position); return 1; }       // 0x0031EA40
static cell n_actorGetDrawRotation(AMX *, const cell *p) { SELF; ACTOR(2); put3(OUT(1), a->rotation); return 1; }       // 0x0031EABC
static cell n_actorGetDrawPitch(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotation[0]); }              // 0x0031EA18
static cell n_actorGetDrawYaw(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotation[1]); }                // 0x0031EB20
static cell n_actorGetDrawRoll(AMX *, const cell *p) { SELF; ACTOR(1); return amx_ftoc(a->rotation[2]); }               // 0x0031EA94
static cell n_actorAddPosition(AMX *, const cell *p) { SELF; ACTOR(2); a->addPositionSim(self->getVector3(p[1])); return 0; }   // 0x0031DAD0
static cell n_actorAddRotation(AMX *, const cell *p) { SELF; ACTOR(2); a->addRotationSim(self->getVector3(p[1])); return 0; }   // 0x0031DB1C
// 0x0031E60C / 0x0031E668: actorGetAxis(n, out[], actor): an axis of the simulated / drawn matrix.
static cell n_actorGetAxis(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->getAxisSim(p[1]); put3(OUT(2), &v.x); return 0; }
static cell n_actorGetAxisDraw(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->getAxis(p[1]); put3(OUT(2), &v.x); return 0; }

// 0x0031DCE0: distance squared to the main camera (Renderer 0 +0xC4).
static cell n_actorCameraDistanceSq(AMX *, const cell *p)
{
	SELF;
	Actor *a = self->getActor(p[1]);
	const f32 *cam = Renderer::getRenderer(0)->cameraPos, *pos = a->positionPtr;
	f32 dx = pos[0] - cam[0], dy = pos[1] - cam[1], dz = pos[2] - cam[2];
	return amx_ftoc(dx * dx + dy * dy + dz * dz);
}

// 0x0031DBC0: actorCacheMatrixInv2D(actor): the matrix of its drawn yaw (rotation[1], the other angles 0)
// and drawn position, inverted into a global (0x003B4AE4) that the 2D drawing uses.
static cell n_actorCacheMatrixInv2D(AMX *, const cell *p);

// ---- properties (the actor's BXML attributes, Actor::getAttribute, vtable) -----------------------------

// 0x0031F304, 0x0031F4F0, 0x0031F640, 0x0031F428, 0x0031F5A4: actorGetProp*(name[], out, actor): true if
// the actor has it. Int and Real convert from the attribute's type; RGB splits one int into 3 cells;
// the string is copied.
template <typename Get> static cell getProp(const cell *p, Get get)
{
	SELF;
	Actor *a = self->getActor(p[3]);
	if (a == nullptr)
		return 0;
	char n[384];
	name(self, n, p[1]);
	BXML::DynamicAttribute attribute(n);
	if (!a->getAttribute(&attribute))
		return 0;
	get(self, attribute, p[2]);
	return 1;
}
static cell n_actorGetPropInt(AMX *, const cell *p) { return getProp(p, [](AMXLoader *s, auto &at, cell o) { *s->getAddr(o, 0) = at.asInt(); }); }
static cell n_actorGetPropReal(AMX *, const cell *p) { return getProp(p, [](AMXLoader *s, auto &at, cell o) { *s->getAddr(o, 0) = amx_ftoc(at.asFloat()); }); }
static cell n_actorGetPropVector(AMX *, const cell *p) { return getProp(p, [](AMXLoader *s, auto &at, cell o) { VEC3 v = at.asVector(); put3(s->getAddr(o, 0), &v.x); }); }
static cell n_actorGetPropRGB(AMX *, const cell *p) { return getProp(p, [](AMXLoader *s, auto &at, cell o) { u32 c = at.asColor(); cell *d = s->getAddr(o, 0); d[0] = c & 0xFF; d[1] = c >> 8 & 0xFF; d[2] = c >> 16 & 0xFF; }); }
static cell n_actorGetPropString(AMX *, const cell *p) { return getProp(p, [](AMXLoader *s, auto &at, cell o) { s->setString((const char *)at.data, o); }); }

// 0x0031EB88: actorGetLastReadProperties(dest[], unused, actor): the properties file it was made from.
static cell n_actorGetLastReadProperties(AMX *, const cell *p) { SELF; ACTOR(3); char s[128]; s[0] = 0; a->getLastReadProperties(s); self->setString(s, p[1]); return 1; }

// ---- model: animations, bones, colours ------------------------------------------------------------------

#define MODEL(i) SELF; Actor *a = self->getActor(p[i]); ModelSet *m = a ? a->model : nullptr; if (m == nullptr) return 0
static cell n_actorFindAnim(AMX *, const cell *p) { MODEL(2); char n[384]; name(self, n, p[1]); return (cell)m->findAnim(n); }     // 0x0031DFA4: an animation (pointer)
static cell n_actorGetAnim(AMX *, const cell *p) { MODEL(2); return (cell)m->getAnimNum(p[1]); }                                   // 0x0031E4E4: by index
static cell n_actorGetNumAnims(AMX *, const cell *p) { MODEL(1); return m->animCount; }                                            // 0x0031ED40 (+0x10)
static cell n_actorFindModel(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[2]); if (!a || !a->model) return -1; char n[384]; name(self, n, p[1]); return a->model->findModelIndex(n); }   // 0x0031E204
static cell n_actorGetModelName(AMX *, const cell *p) { MODEL(3); self->setString(m->name, p[1]); return 1; }                     // 0x0031EC90 (+0x20)
// 0x0031E520 / 0x0031E54C / 0x0031DB68: an animation's frame, length (Float) and "playing" flag (+5).
static cell n_actorGetAnimFrame(AMX *, const cell *p) { Anim *an = (Anim *)p[1]; return an ? amx_ftoc(an->frame()) : 0; }
static cell n_actorGetAnimLength(AMX *, const cell *p) { Anim *an = (Anim *)p[1]; return an ? amx_ftoc(an->length()) : 0; }  // ("actorGetAnimLength: invalid anim in script '%s'")
static cell n_actorAnimIsPlaying(AMX *, const cell *p) { return p[1] ? ((Anim *)p[1])->playing : 0; }
static cell n_actorGetNameOfAnim(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[3]); if (!a || !p[1]) return 0; self->setString(((Anim *)p[1])->name(), p[2]); return 1; }   // 0x0031ECE8
// Bones of model `index`: 0x0031E6C4 index by name (-1), 0x0031ED6C count, 0x0031E944 name, and the bone's
// local position, rotation, scale (0x0031E790, 0x0031E820, 0x0031E8B0): actorGetBoneLocal*(bone, out[],
// model, actor), true when the bone exists.
static cell n_actorGetBoneIdx(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[3]); if (!a || !a->model) return -1; char n[384]; name(self, n, p[1]); return a->model->getModel(p[2])->getBoneIdx(n); }
static cell n_actorGetNumBones(AMX *, const cell *p) { MODEL(2); return m->getModel(p[1])->getNumBones(); }
static cell n_actorGetBoneName(AMX *, const cell *p) { MODEL(5); self->setString(m->getModel(p[4])->getBoneName(p[1]), p[2]); return 1; }
static cell n_actorGetBoneLocalPos(AMX *, const cell *p) { MODEL(4); VEC3 v; if (!m->getModel(p[3])->getBoneLocalPos(p[1], &v)) return 0; put3(OUT(2), &v.x); return 1; }
static cell n_actorGetBoneLocalRot(AMX *, const cell *p) { MODEL(4); VEC3 v; if (!m->getModel(p[3])->getBoneLocalRot(p[1], &v)) return 0; put3(OUT(2), &v.x); return 1; }
static cell n_actorGetBoneLocalScale(AMX *, const cell *p) { MODEL(4); VEC3 v; if (!m->getModel(p[3])->getBoneLocalScale(p[1], &v)) return 0; put3(OUT(2), &v.x); return 1; }
// 0x0031EC04: actorGetModelColor(material[], index, actor): the material colour, bytes reversed (RGBA <-> ABGR).
static cell n_actorGetModelColor(AMX *, const cell *p) { SELF; ACTOR(3); char n[384]; name(self, n, p[1]); return byteswap(a->model->resource->getMaterialColor(n, p[2])); }
// 0x0031DA68: actorAddModelTextureTrans(material[], value, ..., actor): scrolls a material's texture.
static cell n_actorAddModelTextureTrans(AMX *, const cell *p) { SELF; ACTOR(6); char n[384]; name(self, n, p[1]); a->model->addMaterialTextureTranslate(n, p[2]); return 0; }

// ---- layout panes (2D interface; panes are nw::lyt::Pane pointers) ---------------------------------------

// 0x0031E270: actorFindPane(name[], actor): the pane, 0 if none ("[%s] Actor not found!! ( pane: %s, id: %d )").
static cell n_actorFindPane(AMX *, const cell *p) { SELF; char n[384]; name(self, n, p[1]); Actor *a = self->getActor(p[2]); return a ? (cell)a->layout->getRootPane()->FindPaneByName(n, true) : 0; }
static cell n_actorFindBoundingPane(AMX *, const cell *p) { SELF; char n[384]; name(self, n, p[1]); Actor *a = self->getActor(p[2]); return (cell)a->layout->findBoundingPane(a->layout->getRootPane()->FindPaneByName(n, true)); }   // 0x0031E09C
// 0x0031E1B8: actorFindHitPane(pane, x, y, actor): the pane under a point (nw::lyt::FindHitPane).
static cell n_actorFindHitPane(AMX *, const cell *p) { SELF; if (!self->getActor(p[4])) return 0; VEC2 v = {(f32)p[2], (f32)p[3]}; return (cell)nw::lyt::FindHitPane((Pane *)p[1], v); }
static cell n_actorGetPaneName(AMX *, const cell *p) { SELF; if (!p[1]) return 0; self->setString(((Pane *)p[1])->name, p[2]); return 1; }   // 0x0031EEA0 (+0xB8)
static cell n_actorGetPaneParent(AMX *, const cell *p) { return p[1] ? (cell)((Pane *)p[1])->parent : 0; }                              // 0x0031EED8
// 0x0031EEE8 / 0x0031F21C: its translation (the global matrix's column, +0x8C/9C/AC) and size (+0x48, z 0).
static cell n_actorGetPanePos(AMX *, const cell *p) { SELF; Pane *pn = (Pane *)p[1]; cell *o = OUT(2); o[0] = pn->mtx[0][3]; o[1] = pn->mtx[1][3]; o[2] = pn->mtx[2][3]; return 1; }
static cell n_actorGetPaneSize(AMX *, const cell *p) { SELF; Pane *pn = (Pane *)p[1]; cell *o = OUT(2); o[0] = amx_ftoc(pn->size.x); o[1] = amx_ftoc(pn->size.y); o[2] = 0; return 1; }
// 0x0031EF30 / 0x0031F0A8: a pane's user data (the layout's extended user data, by name): int or string.
static cell n_actorGetPanePropInt(AMX *, const cell *p);
static cell n_actorGetPanePropString(AMX *, const cell *p);
// 0x0031E3AC: actorForEachChildOfPane(pane, function[]): the calling script's function called with each child.
static cell n_actorForEachChildOfPane(AMX *, const cell *p)
{
	SELF;
	Pane *pane = (Pane *)p[1];
	if (pane == nullptr)
		return 0;
	char f[384];
	name(self, f, p[2]);
	int index = self->findPublic(f);
	if (index < 0)
		return 0;
	for (Pane *child : pane->children) {
		AMXState state;
		self->freezeState(&state);
		self->pushArg((cell)child);
		self->callFunction(index);
		self->thawState(&state);
	}
	return 0;
}
static cell n_actorClearCallback(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[2]); if (a && a->layout) a->layout->clearLayoutCallback(); return 0; }   // 0x0031DD40
static cell n_actorDisableFBBinding(AMX *, const cell *) { Graphics::bindFBTexture(0, 0); return 0; }   // 0x0031DD6C

// 0x0031DD84: actorFastReplaceKeyStringf(actor, pane[], withStyle, key[], ...): the text of a key, its "#N"
// replaced (keystring_sprintf), into a text pane, with the text's style when asked.
// 0x0031DF00: actorFastReplaceStringf(actor, pane[], format[], ...): Pawn's strformat into a text pane.
// 0x0031EDA8: actorGetNumKeyStringLineFeeds(actor, key[]): the line feeds of a text.
static cell n_actorFastReplaceKeyStringf(AMX *, const cell *p);
static cell n_actorFastReplaceStringf(AMX *, const cell *p);
static cell n_actorGetNumKeyStringLineFeeds(AMX *, const cell *p);

// ---- life, messages, state -------------------------------------------------------------------------------

static cell n_actorKill(AMX *, const cell *p) { SELF; self->getActor(p[1])->kill(); return 0; }                         // 0x0031F938
static cell n_actorIsVisibleDraw(AMX *, const cell *p) { SELF; return self->getActor(p[1])->visible; }                  // 0x0031F91C
static cell n_actorPrintInfo(AMX *, const cell *p) { SELF; self->getActor(p[1]); return 0; }                            // 0x0031FEA0 (its log is gone)
// 0x00320374: actorSendMessage(actor, message, value): into the actor's script queue, from the caller;
// the target field is the actor argument as given.
static cell n_actorSendMessage(AMX *, const cell *p) { SELF; ACTOR(1); a->script->queueMessage(self->uid, p[1], p[2], p[3]); return 0; }
static cell n_actorReadProperties(AMX *, const cell *p) { SELF; ACTOR(2); char n[384]; name(self, n, p[1]); return a->readProperties(n); }   // 0x0031FF08
static cell n_actorSetFlags(AMX *, const cell *p) { SELF; self->getActor(p[2])->flags = p[1]; return 0; }               // 0x00320590 (+0x2C)
static cell n_actorSetMapType(AMX *, const cell *p) { SELF; self->getActor(p[2])->onMap = p[1]; return 0; }             // 0x0032076C
static cell n_actorSetCacheable(AMX *, const cell *p) { SELF; ACTOR(2); a->setCacheable(p[1] != 0); return 0; }          // 0x003204A8
static cell n_actorSetCollisionCheck(AMX *, const cell *p) { SELF; ACTOR(2); a->setCollisionCheck(p[1]); return 0; }     // 0x003204DC
static cell n_actorSetCollisionType(AMX *, const cell *p) { SELF; ACTOR(2); a->setCollisionType(p[1]); return 0; }       // 0x00320504
static cell n_actorSetCustomFlag(AMX *, const cell *p) { SELF; self->getActor(p[3])->setCustomFlagSim(p[1] & 0xFF, p[2] != 0); return 0; }   // 0x0032052C
static cell n_actorSetCustomValue(AMX *, const cell *p) { SELF; self->getActor(p[3])->setCustomValueSim(p[1] & 0xFF, amx_ctof(p[2])); return 0; }   // 0x00320564
static cell n_actorSetIdleDistance(AMX *, const cell *p) { SELF; self->getActor(p[2])->setIdleDistance(amx_ctof(p[1])); return 0; }   // 0x003205B4

// ---- position in the world ---------------------------------------------------------------------------------

static cell n_actorMoveTo(AMX *, const cell *p) { SELF; ACTOR(2); a->setPositionSim(self->getVector3(p[1])); return 0; }   // 0x0031FCF4
// 0x0031FBA8 / 0x0031FB18: a point of the actor's frame in the world (simulated / drawn matrix);
// 0x0031FC38: a direction (the drawn matrix's rotation only).
static cell n_actorLocalPosToWorld(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->getMatrixSim()->transform(self->getVector3(p[2])); put3(OUT(1), &v.x); return 0; }
static cell n_actorLocalDrawPosToWorld(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->matrix.transform(self->getVector3(p[2])); put3(OUT(1), &v.x); return 0; }
static cell n_actorLocalVectorToWorld(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->matrix.rotate(self->getVector3(p[2])); put3(OUT(1), &v.x); return 0; }

// ---- animations (Anim pointers: actorFindAnim / actorGetAnim) ----------------------------------------------

// 0x0031FD40: actorPlayAnim(anim): rewinds and plays it, returns its length (Float).
// ("actorPlayAnim: invalid anim in script '%s'")
static cell n_actorPlayAnim(AMX *, const cell *p) { Anim *an = (Anim *)p[1]; if (!an) return 0; an->rewind(); return amx_ftoc(an->play()); }
// 0x0031FE08: every animation of the model, returns the longest length.
static cell n_actorPlayDefaultAnims(AMX *, const cell *p)
{
	SELF;
	Actor *a = self->getActor(p[1]);
	if (!a || !a->model)
		return 0;
	f32 longest = 0;
	for (int i = 0; i < a->model->animCount; i++) {
		Anim *an = a->model->getAnimNum(i);
		an->rewind();
		longest = max(longest, an->play());
	}
	return amx_ftoc(longest);
}
static cell n_actorSetAnimFrame(AMX *, const cell *p) { Anim *an = (Anim *)p[1]; if (an) { an->setFrame(amx_ctof(p[2])); an->setSpeed(0); } return 0; }   // 0x003203FC (vtable +0, +4)
static cell n_actorSetAnimSpeed(AMX *, const cell *p) { if (p[1]) ((Anim *)p[1])->setSpeed(amx_ctof(p[2])); return 0; }    // 0x00320448
static cell n_actorSetAnimWeight(AMX *, const cell *p) { if (p[1]) ((Anim *)p[1])->setWeight(amx_ctof(p[2])); return 0; }  // 0x00320478

// ---- model -------------------------------------------------------------------------------------------------

// 0x00320790: actorSetModel(name[], flag1, flag2, actor): "" keeps the model; true if the actor exists.
static cell n_actorSetModel(AMX *, const cell *p) { SELF; ACTOR(4); char n[384]; name(self, n, p[1]); if (strcmp(n, "") != 0) a->setModel(n, p[2] != 0, p[3] != 0); return 1; }
static cell n_actorSetModelLayer(AMX *, const cell *p) { SELF; ACTOR(2); a->model->setLayer((u8)p[1]); return 0; }   // 0x003208C4
// 0x00320820 / 0x003208F8: a material's colour / specular colour: (material[], index, r, g, b, a, actor).
static cell n_actorSetModelColor(AMX *, const cell *p) { SELF; ACTOR(7); char n[384]; name(self, n, p[1]); a->model->resource->setMaterialColor(n, p[2], rgba(p[3], p[4], p[5], p[6])); return 0; }
static cell n_actorSetModelSpecular(AMX *, const cell *p) { SELF; ACTOR(7); char n[384]; name(self, n, p[1]); a->model->resource->setSpecularColor(n, p[2], rgba(p[3], p[4], p[5], p[6])); return 0; }
// 0x0032099C: actorSetModelTexture(texture[], replacement[], actor) (ModelResource::replaceTexture);
// 0x00320A1C: actorSetModelTextureToFB(texture[], actor): the texture shows a frame buffer.
static cell n_actorSetModelTexture(AMX *, const cell *p) { SELF; ACTOR(3); char t[384], r[384]; name(self, t, p[1]); name(self, r, p[2]); a->model->resource->replaceTexture(t, r); return 0; }
static cell n_actorSetModelTextureToFB(AMX *, const cell *p) { SELF; ACTOR(2); char t[384]; name(self, t, p[1]); a->model->resource->textureToFB(t); return 0; }

// ---- layout ------------------------------------------------------------------------------------------------

// 0x003205D8: actorSetLayout(name[], unused, flag, renderer, actor); true if the actor exists.
static cell n_actorSetLayout(AMX *, const cell *p) { SELF; ACTOR(5); char n[384]; name(self, n, p[1]); a->setLayout(n, p[4], p[3] != 0); return 1; }
static cell n_actorSetLayoutPreCallback(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[2]); if (a && a->layout) { char f[384]; name(self, f, p[1]); a->layout->registerLayoutCallback(f); } return 0; }   // 0x00320648
// 0x0031F958: actorLoadLayoutPaneAnim(pane[], anim[], actor): the layout's animation (loaded if needed),
// rewound and played; returns it.
static cell n_actorLoadLayoutPaneAnim(AMX *, const cell *p)
{
	SELF;
	char pane[384], anim[384];
	name(self, pane, p[1]);
	name(self, anim, p[2]);
	Actor *a = self->getActor(p[3]);
	if (!a || !a->layout)
		return 0;
	LayoutAnim *an = a->layout->findAnim(pane, anim);
	if (an == nullptr)
		an = a->layout->loadAnim(pane, anim);
	if (an != nullptr) {
		an->rewind();
		an->play();
	}
	return (cell)an;
}
// 0x0031FF64 / 0x003202AC: actorReplaceKeyStringf, actorReplaceStringf: as their "Fast" forms (part 1), with
// the layout's text refreshed (replaceString's last argument 1).
static cell n_actorReplaceKeyStringf(AMX *, const cell *p);
static cell n_actorReplaceStringf(AMX *, const cell *p);
// 0x003206AC: actorSetLogStyle(actor, pane[], key[]): a text pane takes the style of a text (the default
// font when it has none).
static cell n_actorSetLogStyle(AMX *, const cell *p);
// Panes: colour (0x00320A7C: one of the pane's vertex colours, bytes reversed), position, rotation, scale
// (0x00320ACC, 0x00320B0C, 0x00320B4C: Layout::setPane*), texture (0x00320B94: "<name>.bclim" from the
// layout's archive into the pane's texture map n), the Mii icon (0x003200E0: actorReplaceMiiImage(pane, ...,
// storeData, n): FaceSystem::createIcon into the pane's texture map n, 64x64).
static cell n_actorSetPaneColor(AMX *, const cell *p) { Material *m = paneMaterial((Pane *)p[1]); m->colors[(p[3] + 1) & 0xFF] = byteswap(p[2]); return 1; }
static cell n_actorSetPanePos(AMX *, const cell *p) { SELF; Pane *pn = (Pane *)p[1]; Layout::getPaneLayout(pn)->setPanePosition(pn, self->getVector3(p[2])); return 1; }
static cell n_actorSetPaneRotation(AMX *, const cell *p) { SELF; Pane *pn = (Pane *)p[1]; Layout::getPaneLayout(pn)->setPaneRotation(pn, self->getVector3(p[2])); return 1; }
static cell n_actorSetPaneScale(AMX *, const cell *p) { SELF; Pane *pn = (Pane *)p[1]; Layout::getPaneLayout(pn)->setPaneScale(pn, self->getVector3(p[2])); return 1; }
static cell n_actorSetPaneTexture(AMX *, const cell *p);
static cell n_actorReplaceMiiImage(AMX *, const cell *p);
// 0x00320C88 / 0x00320D04: a picture pane's texture coordinates (map n, two corners from two vectors) and a
// pane's visibility.
static cell n_actorSetPaneUV(AMX *, const cell *p) { SELF; VEC3 a = self->getVector3(p[2]), b = self->getVector3(p[3]); ((nw::lyt::Picture *)p[1])->SetTexCoord(p[4], texCoordQuad(a, b)); return 1; }
static cell n_actorSetPaneVisible(AMX *, const cell *p) { Pane *pn = (Pane *)p[1]; Layout::getPaneLayout(pn)->setPaneVisibility(pn, p[2] != 0); return 1; }

// ---- setting state -----------------------------------------------------------------------------------------

static cell n_actorSetPosition(AMX *, const cell *p) { SELF; ACTOR(2); a->setPositionSim(self->getVector3(p[1])); return 0; }   // 0x00320E00 (as actorMoveTo)
static cell n_actorSetRotation(AMX *, const cell *p) { SELF; self->getActor(p[2])->setRotationSim(self->getVector3(p[1])); return 0; }   // 0x00321164 (no check)
static cell n_actorSetPitch(AMX *, const cell *p) { SELF; ACTOR(2); a->rotationSim()[0] = amx_ctof(p[1]); a->matrixDirty = true; return 0; }   // 0x00320DC8
static cell n_actorSetYaw(AMX *, const cell *p) { SELF; ACTOR(2); a->rotationSim()[1] = amx_ctof(p[1]); a->matrixDirty = true; return 0; }     // 0x003213CC
static cell n_actorSetRoll(AMX *, const cell *p) { SELF; ACTOR(2); a->rotationSim()[2] = amx_ctof(p[1]); a->matrixDirty = true; return 0; }    // 0x0032112C
static cell n_actorSetScale(AMX *, const cell *p)                                                                                              // 0x003211AC
{
	SELF; ACTOR(2);
	VEC3 s = self->getVector3(p[1]);
	if (s.x != a->scale[0] || s.y != a->scale[1] || s.z != a->scale[2]) {
		memcpy(a->scale, &s, 12);
		a->matrixDirty = true;
	}
	return 0;
}
// 0x00321320: the velocity, and `moving` (+0x42) when it is not zero; 0x003212B4: the torque (+0x104).
static cell n_actorSetVelocity(AMX *, const cell *p) { SELF; ACTOR(2); VEC3 v = self->getVector3(p[1]); memcpy(a->velocity, &v, 12); a->moving = v.x != 0 || v.y != 0 || v.z != 0; return 0; }
static cell n_actorSetTorque(AMX *, const cell *p) { SELF; ACTOR(2); VEC3 v = self->getVector3(p[1]); memcpy(a->torque, &v, 12); return 0; }
static cell n_actorSetVisible(AMX *, const cell *p) { SELF; self->getActor(p[2])->setVisibleSim(p[1] != 0); return 0; }      // 0x003213A0
static cell n_actorSetStatic(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[1]); if (a) a->isStatic = true; return 1; }   // 0x0032128C
static cell n_actorSetParent(AMX *, const cell *p) { SELF; ACTOR(2); a->parent = p[1]; return 1; }                           // 0x00320D3C
static cell n_actorSetUID(AMX *, const cell *p) { SELF; ACTOR(2); a->script->uid = p[1]; return 0; }                         // 0x003212F0
static cell n_actorSetScript(AMX *, const cell *p) { SELF; ACTOR(2); char n[384]; name(self, n, p[1]); a->setScript(n); return 1; }   // 0x00321230
// 0x003210D0: the script that runs the actor during a replay. Its C++ name is Actor::setStasisScript: the
// scripts' logs call that state "stasis" ("[stasis::enterReplayActorOffset]").
static cell n_actorSetReplayScript(AMX *, const cell *p) { SELF; ACTOR(2); char n[384]; name(self, n, p[1]); a->setStasisScript(n); return 1; }
static cell n_actorSetPartLayer(AMX *, const cell *p) { SELF; ACTOR(3); char n[384]; name(self, n, p[1]); a->model->setLayer((u8)p[2], n); return 0; }   // 0x00320D68
static cell n_actorUpdateMatrix(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[1]); if (a) a->updateMatrix(); return 1; }   // 0x00321A3C

// 0x00320E4C, 0x00320EE0, 0x00321028, 0x00320F74: actorSetProp*(name[], value, actor): through the actor's
// own setter (Actor::setAttributeInt/Float/Vector/String), else its common one; true if the actor exists.
template <typename Fill, typename Set> static cell setProp(const cell *p, Fill fill, Set set)
{
	SELF; ACTOR(3);
	char n[384];
	name(self, n, p[1]);
	BXML::DynamicAttribute attribute(n);
	DynamicProperty property = {&attribute};
	fill(self, property, p[2]);
	if (!set(a, property))
		a->setAttributeCommon(&attribute, &property);
	return 1;
}
static cell n_actorSetPropInt(AMX *, const cell *p) { return setProp(p, [](AMXLoader *, auto &pr, cell v) { pr.setInt(v); }, [](Actor *a, auto &pr) { return a->setAttributeInt(&pr); }); }
static cell n_actorSetPropReal(AMX *, const cell *p) { return setProp(p, [](AMXLoader *, auto &pr, cell v) { pr.setFloat(amx_ctof(v)); }, [](Actor *a, auto &pr) { return a->setAttributeFloat(&pr); }); }
static cell n_actorSetPropVector(AMX *, const cell *p) { return setProp(p, [](AMXLoader *s, auto &pr, cell v) { pr.setVector3(s->getVector3(v)); }, [](Actor *a, auto &pr) { return a->setAttributeVector(&pr); }); }
static cell n_actorSetPropString(AMX *, const cell *p) { return setProp(p, [](AMXLoader *s, auto &pr, cell v) { char t[384]; t[0] = 0; s->getString(t, v); pr.setString(t); }, [](Actor *a, auto &pr) { return a->setAttributeString(&pr); }); }

// ---- animations again ------------------------------------------------------------------------------------

static cell n_actorStopAnim(AMX *, const cell *p) { if (p[1]) ((Anim *)p[1])->stop(); return 0; }                 // 0x00321468 (vtable +0x1C)
static cell n_actorStopAllAnims(AMX *, const cell *p) { MODEL(1); for (int i = 0; i < m->animCount; i++) m->getAnimNum(i)->stop(); return 0; }   // 0x00321404

// ---- the world and the actor's frame -----------------------------------------------------------------------

// 0x00321A60 / 0x00321B84: a world point / direction in the actor's frame (its inverse matrix); 0x00321AF0:
// in the 2D frame cached by actorCacheMatrixInv2D (the point's y set to 0 first).
static cell n_actorWorldPosToLocal(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->getInverseMatrix()->transform(self->getVector3(p[2])); put3(OUT(1), &v.x); return 0; }
static cell n_actorWorldVectorToLocal(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 v = a->getInverseMatrix()->rotate(self->getVector3(p[2])); put3(OUT(1), &v.x); return 0; }
static cell n_actorWorldPosToLocal2D(AMX *, const cell *p) { SELF; ACTOR(3); VEC3 w = self->getVector3(p[2]); w.y = 0; VEC3 v = s_matrixInv2D.transform(w); put3(OUT(1), &v.x); return 0; }

// ---- synchronisation and remote calls (synclist.cpp, rpc.cpp) -----------------------------------------------

static cell n_actorSyncOn(AMX *, const cell *p) { SyncList::setActive(p[1] != 0); return 1; }                                   // 0x00321934
static cell n_actorSyncRegister(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[1]); SyncList::registerActor(a); return SyncList::actorGetID(a); }   // 0x003219B8
static cell n_actorSyncRegisterRemote(AMX *, const cell *p) { SELF; Actor *a = self->getActor(p[3]); SyncList::registerActorRemote(a, p[1], (u8)p[2]); return SyncList::actorGetID(a); }   // 0x003219E0
static cell n_actorSyncRemove(AMX *, const cell *p) { SELF; if (Session::isActive()) SyncList::removeActor(self->getActor(p[1])); return 1; }   // 0x00321A10
// 0x00321950: a property synced (its first 32 characters).
static cell n_actorSyncProperty(AMX *, const cell *p) { SELF; char n[384], short_[32]; name(self, n, p[1]); Actor *a = self->getActor(p[2]); strncpy(short_, n, 32); return SyncList::actorSyncProperty(a, short_); }
// 0x00321494 / 0x00321624 / 0x003217CC: actorSyncCallPublic(function[], ...) and its Directed (node first)
// and f (format) forms: the calling actor's function, on the copies of it on every console (or one node),
// through RPC::callPublic with this console as owner. Only for a synced actor ("%s calling %s(): Only synced
// actors can call actorSyncCallPublic. I'm not an actor./I'm not synced.").
static cell n_actorSyncCallPublic(AMX *, const cell *p);
static cell n_actorSyncCallPublicDirected(AMX *, const cell *p);
static cell n_actorSyncCallPublicf(AMX *, const cell *p);
