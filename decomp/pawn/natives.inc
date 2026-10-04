/* Pawn prototypes of the natives the game registers (romfs:/amx scripts -> C++).
 *
 * Written from the C++ implementations (decomp/raw/source/amx/*.cpp, n_<name> functions);
 * parameter names are ours. tools/amxdec.py reads these prototypes to type the arguments at call
 * sites (strings, arrays, Float, by-reference), and falls back on the types inferred automatically
 * by tools/native_types.py for the natives that are not listed here.
 *
 * Conventions of the game:
 *  - `actor` is an actor id (index in the World's actor pool); 0 means the actor that runs the
 *    calling script (AMXLoader::getActor). It is the last parameter of almost every actor* native.
 *  - `uid` designates a script: below 1000 it is an actor id (that actor's script), otherwise the
 *    UID a script gave itself with sysSetUID() (AMXLoader::uidToAmx). 0 is the calling script.
 *  - Vectors are Float:v[3]; colours are r, g, b, a cells (0-255).
 *  - Variadic arguments are passed by reference, as always in Pawn.
 */

/* UIDs the scripts give themselves with sysSetUID() (the values are the game's; names are ours,
 * after the scripts that set them). Several scripts may share one: the call goes to the first one
 * loaded (AMXLoader::uidToAmx walks the list of loaders). */
enum UID {
    UID_MODE = 10000,                  // the running mode_* script
    UID_PERISCOPE_MOVE = 10001,        // periscope_move
    UID_HUD = 10010,                   // hud
    UID_PAUSE = 10011,                 // pause, peri_pause
    UID_HUD_PAUSE = 10012,             // hud_pause
    UID_SURFACE_VEHICLE = 10050,       // surface_sub, surface_ship, surface_cannon, ... (surface mode units)
    UID_PLAYER = 10100,                // pscope_player, tank, tankv2
    UID_CAMERA = 10101,                // camera_scope, camera_tank
    UID_SURFACE_CAMERA = 10102,        // surface_camera
    UID_MESSAGE_QUEUE = 11010,         // message_queue
    UID_PERISCOPE_WINDOW = 11020,      // periscope_window
    UID_GAME_STATE = 11030,            // game_state
    UID_SONAR = 11050,                 // sonar
    UID_MORSE = 11060,                 // morse
    UID_WORLD_MAP = 11070,             // world_map
    UID_PLAYER_LABEL = 11080,          // player_label
    UID_SURFACE_MORSE = 11090,         // surface_morse
    UID_CONTROLS = 11100,              // controls
    UID_SURFACE_TREASURE_BOX = 11150,  // surface_treasure_box
    UID_NETPLAY_DUMMY_SUB = 20100,     // netplay_dummy_sub
}

/* Button masks returned by sysGetButtons*() (the game's own layout: the stick bits differ from the
 * SDK's), mapped to actions by controls.inc. Names after the engine globals "controls.<button>". */
enum BUTTON {
    BUTTON_A = 0x1,
    BUTTON_B = 0x2,
    BUTTON_SELECT = 0x4,
    BUTTON_START = 0x8,
    BUTTON_KEY_RIGHT = 0x10,
    BUTTON_KEY_LEFT = 0x20,
    BUTTON_KEY_UP = 0x40,
    BUTTON_KEY_DOWN = 0x80,
    BUTTON_R = 0x100,
    BUTTON_L = 0x200,
    BUTTON_X = 0x400,
    BUTTON_Y = 0x800,
    BUTTON_DEBUG = 0x1000,
    BUTTON_RESERVED = 0x2000,
    BUTTON_ZL = 0x4000,
    BUTTON_ZR = 0x8000,
    BUTTON_STICK_RIGHT = 0x10000,
    BUTTON_STICK_LEFT = 0x20000,
    BUTTON_STICK_UP = 0x40000,
    BUTTON_STICK_DOWN = 0x80000,
    BUTTON_EXTRA_STICK_RIGHT = 0x100000,   // C-stick (New 3DS) / Circle Pad Pro
    BUTTON_EXTRA_STICK_LEFT = 0x200000,
    BUTTON_EXTRA_STICK_UP = 0x400000,
    BUTTON_EXTRA_STICK_DOWN = 0x800000,
}

/* ---- amxsys: engine globals ------------------------------------------------------------------
 * Named values shared by every script (and set by the C++ side, e.g. "system.thisframetime"):
 * a hash table of 4096 buckets, names up to 64 characters (amxSysSetGlobal / amxSysGetGlobal). */
native sysGetGlobal(const name[]);                                   // 0 if the global does not exist
native sysSetGlobal(const name[], value);
native sysGetGlobalArray(const name[], dest[], size, offset = 0);     // offset: first cell of dest written
native sysSetGlobalArray(const name[], const source[], size, offset = 0);

/* ---- amxsys: scripts ---- */
native sysCallPublic(UID:uid, const function[], ...);                    // calls a public function of another script
native sysCallPublicf(UID:uid, const function[], const format[], ...);   // format: one letter per argument, s = string
native sysCallPublicDelayed(UID:uid, delay, const function[], ...);
native sysSetModeScript(const mode[]);                               // next mode script, loaded when this one ends
native sysSetUID(UID:uid);                                               // UID of the calling script (>= 1000)
native sysGetUID();
native sysNotify(const event[], ...);                                // calls `event` in every observer
native sysObserve(UID:uid);                                              // the calling script observes `uid`
native sysObserveSystem();
native sysUnobserveSystem();
native sysSendMessage(UID:uid, message, value, flags);                   // queue of 8 messages per script

/* ---- amxsys: input ----
 * Button masks of the controller (System::getController(), one 0x14-byte record per controller). */
native BUTTON:sysGetButtonsClicked(controller = 0);                        // pressed this frame
native BUTTON:sysGetButtonsDown(controller = 0);                           // held
native BUTTON:sysGetButtonsRepeated(controller = 0);                       // pressed, with key repeat
native sysGetTouchPad(position[2]);                                  // returns true while the screen is touched
native sysGetStick(stick[]);
native Float:sysGetGyroBearing();
native sysCheckExtraPadConnected(state[]);                           // Circle Pad Pro
native sysCheckExtraPadBattery(state[]);
native sysExtraPadStartSampling();
native sysExtraPadStopSampling();
native sysShowExtraPadCalibration();

/* ---- amxsys: system ---- */
native Float:sysReadSystemTime();                                    // seconds since start-up (System::getRunningTimeInSeconds)
native sysGetFrameNum();
native sysIsPaused();
native sysSetPaused(bool:paused);
native sysSetIgnorePause();
native sysEnableSleep(bool:enable);                                  // closing the console puts it to sleep
native sysIsSleepEnabled();
native sysEnableHomeButton(bool:enable);
native sysIsHomeButtonEnabled();
native sysGetVersionChecksum();                                     // CRC-32 of the build revision (matchmaking attribute 3)
native sysGetYear();
native sysGetMonth();
native sysGetDay();
native sysGetHour();
native sysGetMinute();
native sysGetRandomSeed();                                           // from the current date and time
native sysDumpProfile();                                             // debug, empty in the retail build
native sysDumpLog();                                                 // debug, empty
native sysPrintStats();                                              // debug, empty
native sysDumpModels();
native sysGetTimerProfiles();
native sysReadTimerProfileLast(index, profile);

/* ---- amxsys: text ---- */
native sysGetString(dest[], const textId[], size = sizeof dest);     // localised text, or textId if missing; size is not read
native sysLoadStrings(const file[]);
native sysGetNickname(dest[]);                                       // owner's name (nn::cfg)
native sysGetLanguage(dest[]);
native sysGetNumGlyphsUTF8(const string[]);
native sysGetSubstringUTF8(dest[], source[], start, count);
native sysShowKeyboard(dest[], maxChars, mode);                     // software keyboard
native sysDoGetStringFilteredThread(const string[], a, b, c);        // profanity filter, in a thread

/* ---- amxsys: save data ---- */
native sysSaveDataSave(const file[], size);
native sysSaveDataClear(const file[]);
native sysSaveDataBusy();
native sysSetSaving(bool:saving);

/* ---- amxsys: Mii, friends, parental controls ---- */
native sysUpdateMii(store[], index, name[], bool:a, unknown, bool:select);
native sysSetMiiStoreData(store[], index, bool:flag);
native sysGetStoreDataName(store[], name[], bool:a, bool:b);
native sysSendMii(...);
native sysIsFriend(principalId);
native sysGetCoppaRestriction();
native sysIsCoppaSupported();
native sysIsCoppaPINAuth();
native sysAuthCoppaPIN();
native sysIsRestrictPhotoExchange();
native sysEulaConfirm();
native sysShowErrEULA(errorCode);

/* ---- amxsys: shop and add-on content (NsubShop, nn::ec) ---- */
native sysDLCCheckPaidForFullVer();
native sysDLCIsItemPurchased(item);
native sysDLCIsItemPurchasable(item);
native sysDLCPurchaseItem(item);
native sysDLCRedownloadItem(item);
native sysDLCGetItemPriceString(item, dest[]);
native sysDLCGetBalanceString(dest[]);
native sysDLCCheckCondition(condition);
native sysDLCUpdateCondition();
native sysDLCCheckLastResult();
native sysDLCWaitThread();
native sysDLCInitializeMetaDataReader();
native sysDLCFinalizeMetaDataReader();
native sysDLCCreateCatalog();
native sysDLCDestroyCatalog();
native sysDLCGetBalanceAsync();
native sysDLCGetContentSetListAsync();
native sysDLCValidateSession();
native sysDLCInvalidateSession();
native sysDLCAcSetupConnect();
native sysDLCAcTryConnect();
native sysDLCAcIsConnected();
native sysDLCAcDisconnect();
native sysDLCAddBalance();
native sysDLCDeleteItemAsync(item);

/* ---- amxactor: properties ----
 * Actor properties are the attributes of its BXML node (worlds/*.bxml), plus dynamic ones. */
native actorGetPropInt(const name[], &value, actor = 0);             // returns true if the property exists
native actorGetPropReal(const name[], &Float:value, actor = 0);
native actorGetPropString(const name[], dest[], actor = 0);
native actorGetPropVector(const name[], Float:value[3], actor = 0);
native actorGetPropRGB(const name[], rgb[], actor = 0);
native actorSetPropInt(const name[], value, actor = 0);
native actorSetPropReal(const name[], Float:value, actor = 0);
native actorSetPropString(const name[], const value[], actor = 0);
native actorSetPropVector(const name[], const Float:value[3], actor = 0);
native actorReadProperties(const file[], actor = 0);                // loads a properties file into the actor
native actorGetLastReadProperties(dest[], unused, actor = 0);
native actorSyncProperty(const name[], actor = 0);                  // replicate the property over the network

/* ---- amxactor: identity and life ---- */
native actorGetID();                                                 // the calling script's actor
native actorGetScript(dest[]);                                       // name of the calling script
native actorSetScript(const script[], actor = 0);
native actorGetParent(actor = 0);
native actorSetParent(parent, actor = 0);
native actorKill(actor = 0);
native actorSetStatic(actor = 0);
native actorGetCacheable(actor = 0);
native actorSetCacheable(bool:cacheable, actor = 0);
native actorSetIdleDistance(Float:distance, actor = 0);              // beyond it the actor is not updated
native actorCameraDistanceSq(actor = 0);
native actorGetCustomFlag(bit, actor = 0);                          // bits of Actor::customFlags
native actorSetCustomFlag(bit, bool:set, actor = 0);
native Float:actorGetCustomValue(index, actor = 0);
native actorSetCustomValue(index, Float:value, actor = 0);

/* ---- amxactor: transform ("Draw" variants: the interpolated values used for rendering) ---- */
native actorGetPosition(Float:position[3], actor = 0);               // returns false if there is no such actor
native actorSetPosition(const Float:position[3], actor = 0);
native actorAddPosition(const Float:offset[3], actor = 0);
native actorMoveTo(const Float:position[3], actor = 0);
native actorGetRotation(Float:rotation[3], actor = 0);               // pitch, yaw, roll
native actorSetRotation(const Float:rotation[3], actor = 0);
native actorAddRotation(const Float:offset[3], actor = 0);
native Float:actorGetYaw(actor = 0);
native Float:actorGetPitch(actor = 0);
native actorSetYaw(Float:yaw, actor = 0);
native actorSetPitch(Float:pitch, actor = 0);
native actorSetRoll(Float:roll, actor = 0);
native actorSetScale(const Float:scale[3], actor = 0);
native actorGetAxis(axis, Float:vector[3], actor = 0);               // axis of the actor's matrix
native actorGetDrawPosition(Float:position[3], actor = 0);
native actorGetDrawRotation(Float:rotation[3], actor = 0);
native Float:actorGetDrawYaw(actor = 0);
native Float:actorGetDrawPitch(actor = 0);
native actorUpdateMatrix(actor = 0);
native actorCacheMatrixInv2D(actor = 0);
native actorLocalPosToWorld(Float:dest[3], const Float:local[3], actor = 0);
native actorLocalDrawPosToWorld(Float:dest[3], const Float:local[3], actor = 0);
native actorLocalVectorToWorld(Float:dest[3], const Float:local[3], actor = 0);
native actorWorldPosToLocal(Float:dest[3], const Float:world[3], actor = 0);
native actorWorldPosToLocal2D(Float:dest[3], const Float:world[3], actor = 0);
native actorWorldVectorToLocal(Float:dest[3], const Float:world[3], actor = 0);

/* ---- amxactor: physics and collision ---- */
native actorGetVelocity(Float:velocity[3], actor = 0);
native actorSetVelocity(const Float:velocity[3], actor = 0);
native actorSetTorque(const Float:torque[3], actor = 0);
native actorGetCollisionType(actor = 0);
native actorSetCollisionType(type, actor = 0);
native actorSetCollisionCheck(check, actor = 0);

/* ---- amxactor: model ---- */
native actorSetModel(const model[], bool:a, bool:b, actor = 0);
native actorSetVisible(bool:visible, actor = 0);
native actorIsVisibleDraw(actor = 0);
native actorSetModelColor(const material[], slot, r, g, b, a, actor = 0);
native actorGetModelColor(const material[], rgb[], actor = 0);
native actorSetModelTexture(const texture[], const replacement[], actor = 0);
native actorAddModelTextureTrans(const material[], index, Float:u, Float:v, unused, actor = 0);
native actorSetModelLayer(layer, actor = 0);
native actorSetPartLayer(const part[], layer, actor = 0);

/* ---- amxactor: animations (handles of model or layout animations) ---- */
native actorFindAnim(const name[], actor = 0);                       // model animation
native actorLoadLayoutPaneAnim(const pane[], const animation[], actor = 0);
native Float:actorPlayAnim(animation);                               // starts it, returns its length
native actorStopAnim(animation);
native actorSetAnimFrame(animation, Float:frame);
native actorSetAnimSpeed(animation, Float:speed);
native Float:actorGetAnimLength(animation);
native actorAnimIsPlaying(animation);

/* ---- amxactor: layouts (2D interface of an actor, NintendoWare panes) ---- */
native actorSetLayout(const layout[], unused, bool:flag, value, actor = 0);
native actorFindPane(const name[], actor = 0);                       // pane handle, 0 if not found
native actorFindHitPane(rootPane, x, y, actor = 0);                  // pane under a touch position
native actorSetPaneVisible(pane, bool:visible);
native actorSetPanePos(pane, const Float:position[3]);
native actorGetPanePos(pane, Float:position[3]);
native actorSetPaneRotation(pane, const Float:rotation[3]);
native actorSetPaneScale(pane, const Float:scale[3]);
native actorSetPaneColor(pane, index, color);
native actorSetPaneUV(pane, const Float:a[], const Float:b[], index);
native actorSetPaneTexture(pane, const texture[], index, actor = 0);
native actorReplaceStringf(actor, const textBox[], const format[], ...);
native actorFastReplaceStringf(actor, const textBox[], const format[], ...);
native actorReplaceKeyStringf(actor, const textBox[], value, const textId[]);
native actorFastReplaceKeyStringf(actor, const textBox[], value, const textId[]);

/* ---- amxactor: network replication (SyncList) ---- */
native actorSyncRegister(actor = 0);                                 // returns the sync id
native actorSyncRemove(actor = 0);
native actorIsSynced(actor = 0);
native actorGetSyncID(actor = 0);                                    // -1 if not synchronised
native actorGetFromSyncID(syncId, node);
native actorGetSyncController(actor = 0);                            // node id of the console that owns it
native actorSyncCallPublic(const function[], ...);                   // on every copy of the calling actor
native actorSyncCallPublicDirected(node, const function[], ...);
native actorSyncCallPublicf(const function[], const format[], ...);

/* ---- amxworld ---- */
native worldLoad(const world[], flags);                              // worlds/<world>.bxml
native worldNewActor();                                              // id of a free actor
native worldFindActor(const name[]);                                 // 0 if not found
native worldFindActorUID(UID:uid);
native worldFindActors(found[], const Float:center[3], unused, max, filter);
native worldFindActorsSorted(found[], const Float:center[3], unused, max, filter);
native worldFindClosestActor(const Float:position[3], unused, filter);
native worldClipLine(const Float:from[3], const Float:to[3], result, mask);
native worldGetHeightAt(value, unused, Float:position[], mask);
native worldLogExplosion(const type[], const Float:position[3], value);
native worldIsPlayingReplay();
native worldGetReplayFramesRemaining();
native worldCacheSuspended();                                        // always 0
native worldSetShowFlags(flags);                                     // debug, empty
native worldIsGroupVisible(group);
native worldShowGroup(group, bool:show);

/* ---- amxnet: multiplayer session (Pia; local wireless or Internet) ---- */
native netInit(connection);                                          // 0 local wireless, 1 Internet
native netIsInitialized();
native netIsActive();
native netGetStatus();
native netScan();
native netFinalize();
native netFinalizePIA();
native netLeaveSession();
native netAbort(bool:flag);
native netIsMaster();                                                // this console hosts the session
native netGetNodeId();                                               // -1 outside a session
native netGetNodeCount();
native netGetNodeMax();                                              // 11
native netGetNodeIdFromIdx(index);
native netGetPID();                                                  // principal id (Internet)
native netGetSessionTime(time[2]);
native netGetSessionTimeLo();
native netCallPublic(UID:target, const function[], ...);                 // remote procedure call (RPC::callPublic)
native netCallPublicf(UID:target, const function[], const format[], ...);
native netSetBroadcastData(const data[]);
native netSetParticipation(bool:open);
native netSetTeamRegistered(team);
native netGetLastCustomFailure();
native inetSetAttribute(index, value);                               // NEX matchmaking attribute (see docs/online.md)

/* ---- amxgfx ---- */
native gfxSelectRenderer(mask);                                      // renderers the next gfx* calls apply to
native gfxCameraLookAt(const Float:eye[3], const Float:target[3], const Float:up[3]);
native gfxCameraSetFOV(Float:fov);
native gfxCameraSetZClip(Float:near, Float:far);
native gfxCameraSetULCD(Float:a, Float:b);                           // stereoscopic 3D parameters
native gfxCameraSetWorldOffset(const Float:offset[3]);
native gfxFadeIn();
native gfxFadeOut();
native gfxIsFading();
native gfxBlackout();
native gfxShowLoadingIcon(bool:show);
native gfxChooseAdvice();
native gfxPrintStringf(x, y, const format[], ...);                   // debug text
native gfxAddMarker(const Float:position[3]);
native gfxDrawLine(const Float:from[3], const Float:to[3], const colour[]);

/* ---- amxsound (DsSubAudioMgr) ---- */
native sndSE(sound, unused = 0, bool:inReplay = false);              // sound effect; skipped during replays unless inReplay
native sndSEDistance(sound, unused1, unused2, bool:inReplay = false);
native sndLevSE(sound);
native sndLevSEDistance(sound);
native sndVoice(voice);
native sndBGMInt(music);
native sndStopBGM();
native Float:sndCalcCameraPan(const Float:position[3]);

/* ---- amxeffects ---- */
native fxParticleAdd(const effect[], const Float:position[3], const Float:rotation[3], const Float:scale[3], a, b);
native fxParticlePosition(particle, const Float:position[3]);
native fxParticleRotation(particle, const Float:rotation[3]);
native fxParticleScale(particle, const Float:scale[3]);
native fxParticlePlay(particle);
native fxParticleStop(particle);
native fxParticleKill(particle);
native fxParticleUpdate(particle);
native fxParticleIsActive(particle);
native fxBubbleAdd(const Float:position[3], const Float:velocity[3]);
native fxBubbleAddMultiple(count, const Float:position[3], const Float:a[3], const Float:b[3]);
native fxOilAdd(const Float:a[3], const Float:b[3], const Float:c[3]);
native fxFishAvoid(const Float:position[3], const Float:a[3]);
native fxTriggerObjectFade(actor, unused, bool:flag);
native fxObjectFadeFlash(actor);
native Float:fxObjectFadeGetVis(actor);
native fxTorpedoTrailAddActor(actor, unused, bool:flag);
native fxTorpedoTrailRemoveActor(actor, bool:flag);

/* ---- amxvector: 3D vectors (Float:v[3]) ---- */
native floatvecset(Float:vector[3], Float:x, Float:y, Float:z);
native floatveczero(Float:vector[3]);
native floatvecadd(Float:vector[3], const Float:add[3]);             // vector += add
native floatvecsub(Float:vector[3], const Float:sub[3]);             // vector -= sub
native floatvecsubto(Float:dest[3], const Float:a[3], const Float:b[3]);   // dest = a - b
native floatvecmul(Float:vector[3], const Float:mul[3]);
native floatvecdiv(Float:vector[3], const Float:div[3]);
native floatvecscale(Float:vector[3], Float:scale);
native floatvecaddscale(Float:vector[3], const Float:add[3], Float:scale);    // vector += add * scale
native floatveccopyscale(Float:dest[3], const Float:source[3], Float:scale);  // dest = source * scale
native Float:floatvecdot(const Float:a[3], const Float:b[3]);
native floatveccross(Float:dest[3], const Float:a[3], const Float:b[3]);
native Float:floatveclength(const Float:vector[3]);
native floatvecnormalize(Float:dest[3], const Float:source[3]);
native floatvecrotrad(Float:dest[3], const Float:a[3], const Float:b[3]);

/* ---- float (float.inc of Pawn 3.3, plus the game's own additions) ---- */
native Float:float(value);
native Float:strfloat(const string[]);
native Float:floatmul(Float:oper1, Float:oper2);
native Float:floatdiv(Float:dividend, Float:divisor);
native Float:floatadd(Float:oper1, Float:oper2);
native Float:floatsub(Float:oper1, Float:oper2);
native Float:floatfract(Float:value);
native floatround(Float:value, method = 0);
native floatcmp(Float:oper1, Float:oper2);
native Float:floatsqroot(Float:value);
native Float:floatpower(Float:value, Float:exponent);
native Float:floatlog(Float:value, Float:base = 10.0);
native Float:floatsin(Float:value, mode = 0);
native Float:floatcos(Float:value, mode = 0);
native Float:floattan(Float:value, mode = 0);
native Float:floatabs(Float:value);
native Float:floatatan2(Float:y, Float:x);
native Float:floatclamp(Float:value, Float:min, Float:max);
native Float:floatrnd();                                             // 0.0 <= x < 1.0, step 0.0001

/* ---- core, string, console (standard Pawn 3.3 natives) ---- */
native random(max);
native setrandomseed(seed);
native clamp(value, min, max);
native min(value1, value2);
native max(value1, value2);
native strlen(const string[]);
native strcopy(dest[], const source[], maxlength = sizeof dest);
native strcat(dest[], const source[], maxlength = sizeof dest);
native strmid(dest[], const source[], start, end, maxlength = sizeof dest);
native strcmp(const string1[], const string2[], bool:ignorecase = false, length = cellmax);
native strfind(const string[], const sub[], bool:ignorecase = false, index = 0);
native strval(const string[], index = 0);
native valstr(dest[], value, bool:pack = true);
native strformat(dest[], size, bool:pack, const format[], ...);
native memcpy(dest[], const source[], index, numbytes, maxlength);
native print(const string[]);
native printf(const format[], ...);
native LOG(const format[], ...);
native WARNING(const format[], ...);
native ERROR(const format[], ...);

/* ---- amxxml: BXML access from the scripts ---- */
native xmlLoad(const file[], root[]);
native xmlGetRootNode(document);
native xmlNodeChild(node);
native xmlNodeSibling(node);
native xmlNodeFind(node, const name[]);
native xmlNodeGetName(node, dest[]);
native xmlNodeGetInt(node, const attribute[], &value);
native xmlNodeGetRGB(node, const attribute[], rgb[]);
native xmlNodeGetString(node, const attribute[], dest[]);
native xmlNodeSetInt(node, const attribute[], value);

/* ---- amxdynamics ---- */
native dynamicsUpdateN(Float:a[], Float:b[], Float:c[], Float:d[], Float:e, Float:f, Float:g);
