// source/amx/amxgfx.cpp (amxgfx.o): the graphics natives of the scripts (natives_Gfx, amx_GfxInit
// 0x00319A6C): cameras, lights, fog, fades, icons, and the developers' debug drawing. Most apply to every
// active renderer (Renderer::isActive over Renderer::getNumRenderers, the renderers chosen by
// gfxSelectRenderer).
//
// Reconstructed by hand from decomp/raw/source/amx/amxgfx.cpp and the disassembly. Not compilable on its own.

#define SELF AMXLoader *self = AMXLoader::getCurrentLoader()
#define FOR_ACTIVE(r) for (int i_ = 0; i_ < Renderer::getNumRenderers(); i_++) if (Renderer *r = Renderer::getRenderer(i_); r->isActive())

// ---- renderers -------------------------------------------------------------------------------------------

// 0x003256A4: gfxSelectRenderer(mask): the renderers the calling script's commands go to (remembered by the
// script, AMXLoader +rendererMask); 0x00325C6C gfxVisibleRenderer(mask): those drawn.
static cell n_gfxSelectRenderer(AMX *, const cell *p) { Renderer::setActiveMask(p[1]); AMXLoader::getCurrentLoader()->rendererMask = p[1]; return 0; }
static cell n_gfxVisibleRenderer(AMX *, const cell *p) { Renderer::setVisibleMask(p[1]); return 0; }
static cell n_gfxSetDrawOrder(AMX *, const cell *p) { s_drawOrder = p[1]; return 0; }                       // 0x003256C8 (0x0038E618)
static cell n_gfxSetLowerScreenDrawRate(AMX *, const cell *p) { s_lowerScreenDrawRate = p[1]; return 0; }   // 0x00325B54 (0x0038E620)
// 0x00324F14: gfxClearColor(r, g, b, clearColour, clearDepth).
static cell n_gfxClearColor(AMX *, const cell *p) { FOR_ACTIVE(r) { r->clearColor = rgba(p[1], p[2], p[3], 255); r->clearsColor = p[4] != 0; r->clearsDepth = p[5] != 0; } return 0; }
static cell n_gfxSetWaterlineCulling(AMX *, const cell *p) { FOR_ACTIVE(r) r->waterlineCulling = p[1] != 0; return 0; }   // 0x00325B6C (+0x115C)
static cell n_gfxEnableEffect(AMX *, const cell *p) { EffectManager::activateEffect((u8)p[1]); return 0; }   // 0x0032516C
// 0x00325C04: gfxSoftReset(): bubbles, the game's clock, and the active renderers reset.
static cell n_gfxSoftReset(AMX *, const cell *) { Bubbles::reset(); World::resetGameTime(); FOR_ACTIVE(r) r->reset(); return 0; }

// ---- camera (Renderer +0xC0: the camera; its parameters below) -----------------------------------------------

static cell n_gfxCameraLookAt(AMX *, const cell *p) { SELF; VEC3 eye = self->getVector3(p[1]), at = self->getVector3(p[2]), up = self->getVector3(p[3]); FOR_ACTIVE(r) r->camera.lookat(eye, at, up); return 0; }   // 0x00324B74
// 0x00324C98: gfxCameraProjection3D(Float:near, Float:far, Float:fov, Float:aspect): perspective (mode 2).
// 0x00324C20: gfxCameraProjection2D(near, far, left, right, bottom, top): orthographic (mode 1).
static cell n_gfxCameraProjection3D(AMX *, const cell *p) { FOR_ACTIVE(r) { r->near = amx_ctof(p[1]); r->far = amx_ctof(p[2]); r->fov = amx_ctof(p[3]); r->aspect = amx_ctof(p[4]); r->projection = 2; } return 0; }
static cell n_gfxCameraProjection2D(AMX *, const cell *p) { FOR_ACTIVE(r) { r->near = amx_ctof(p[1]); r->far = amx_ctof(p[2]); memcpy(r->ortho, &p[3], 16); r->projection = 1; } return 0; }
static cell n_gfxCameraSetFOV(AMX *, const cell *p) { FOR_ACTIVE(r) r->fov = amx_ctof(p[1]); return 0; }                                    // 0x00324D10
static cell n_gfxCameraSetZClip(AMX *, const cell *p) { FOR_ACTIVE(r) { r->near = amx_ctof(p[1]); r->far = amx_ctof(p[2]); } return 0; }  // 0x00324EA4
static cell n_gfxCameraSetWScale(AMX *, const cell *p) { FOR_ACTIVE(r) r->wScale = amx_ctof(p[1]); return 0; }                              // 0x00324DC8 (+0x120)
// 0x00324D68: gfxCameraSetULCD(Float:a, Float:b): the stereo camera's two parameters (+0x218, +0x21C).
static cell n_gfxCameraSetULCD(AMX *, const cell *p) { FOR_ACTIVE(r) { r->ulcd[0] = amx_ctof(p[1]); r->ulcd[1] = amx_ctof(p[2]); } return 0; }
// 0x00324E20: gfxCameraSetWorldOffset(offset[3]): the world shifted for the camera (its x and z; y 0).
static cell n_gfxCameraSetWorldOffset(AMX *, const cell *p) { SELF; VEC3 o = self->getVector3(p[1]); FOR_ACTIVE(r) { r->worldOffset[0] = o.x; r->worldOffset[1] = 0; r->worldOffset[2] = o.z; } return 0; }

// 0x003247C4: gfxCamProjectToScreenSpace(world[3], out[3], divideDepth): the last active renderer's view and
// projection: x, y in pixels from the centre (half the viewport's size, +0x220), z (divided by w if asked).
static cell n_gfxCamProjectToScreenSpace(AMX *, const cell *p);
// 0x0032496C: gfxCamRayFromTouch(x, y, out[3]): the direction, in the world, of the ray under a point of
// the first active renderer's viewport (the inverse projection, then the camera's matrix).
static cell n_gfxCamRayFromTouch(AMX *, const cell *p);

// ---- lights and fog (the renderer's Scene, +0x113C) ------------------------------------------------------------

static cell n_gfxFindLight(AMX *, const cell *p) { SELF; char n[384]; n[0] = 0; self->getString(n, p[1]); FOR_ACTIVE(r) return (cell)r->scene->findLight(n); return 0; }   // 0x003251C0
// 0x00325814: gfxSetLightColor(light, colour[4]): the light's three colours (+0xCC, +0xDC, +0xEC) all set to
// the RGBA (0..255 -> 0..1), each with its packed form. 0x00325310 gfxGetLightColor: the first, as 0..255.
static cell n_gfxSetLightColor(AMX *, const cell *p);
static cell n_gfxGetLightColor(AMX *, const cell *p);
static cell n_gfxSetLightDirection(AMX *, const cell *p) { SELF; Light *l = (Light *)p[1]; memcpy(l->res->direction, self->getAddr(p[2], 0), 12); return 0; }   // 0x00325A70 (+0x10C)
static cell n_gfxGetLightDirection(AMX *, const cell *p) { SELF; memcpy(self->getAddr(p[2], 0), ((Light *)p[1])->worldDirection, 12); return 0; }        // 0x00325484 (+0x17C)
static cell n_gfxSetLightPosition(AMX *, const cell *p) { SELF; VEC3 v; memcpy(&v, self->getAddr(p[2], 0), 12); FOR_ACTIVE(r) r->scene->setLightPosition(p[1], v); return 0; }   // 0x00325AB4
static cell n_gfxGetLightPosition(AMX *, const cell *p) { SELF; cell *o = self->getAddr(p[2], 0); FOR_ACTIVE(r) { VEC3 v; r->scene->getLightPosition(p[1], &v); memcpy(o, &v, 12); } return 0; }   // 0x003254D0
static cell n_gfxGetLightMapColor(AMX *, const cell *) { return 0; }   // 0x003254C8
// 0x00324634 / 0x00325008: a light attached to (detached from) an actor's model: added to (removed from) the
// model's list of lights, its parent set (cleared).
static cell n_gfxAttachLightToActor(AMX *, const cell *p);
static cell n_gfxDetachLightFromActor(AMX *, const cell *p);
// Fog n of the scene (+0x206C): on/off (0x003256E0), colour (0x0032576C: r, g, b floats, alpha 1),
// colour read (0x00325258).
static cell n_gfxSetFog(AMX *, const cell *p) { FOR_ACTIVE(r) if (Fog *f = r->scene->fogs[p[1]]) f->enable(p[2] != 0); return 0; }
static cell n_gfxSetFogColor(AMX *, const cell *p) { FOR_ACTIVE(r) if (Fog *f = r->scene->fogs[p[1]]) { FogRes *c = f->res; c->color[0] = amx_ctof(p[2]); c->color[1] = amx_ctof(p[3]); c->color[2] = amx_ctof(p[4]); c->color[3] = 1.0f; } return 0; }
static cell n_gfxGetFogColor(AMX *, const cell *p) { SELF; FOR_ACTIVE(r) if (Fog *f = r->scene->fogs[p[1]]) memcpy(self->getAddr(p[2], 0), f->res->color, 12); return 0; }

// ---- fades and icons (fader.cpp) ---------------------------------------------------------------------------------

static cell n_gfxFadeIn(AMX *, const cell *) { Fader::startFade(FADE_IN); return 0; }          // 0x00325184
static cell n_gfxFadeOut(AMX *, const cell *) { Fader::startFade(FADE_OUT); return 0; }        // 0x00325198
static cell n_gfxFadeWipe3D(AMX *, const cell *) { Fader::startFade(FADE_FLASH); return 0; }   // 0x003251AC
static cell n_gfxBlackout(AMX *, const cell *) { Fader::blackout(); return 0; }                 // 0x003247B4
static cell n_gfxIsBlackout(AMX *, const cell *) { return Fader::isBlackout(); }                // 0x002E3100
static cell n_gfxIsFading(AMX *, const cell *) { return Fader::isFading(); }                    // 0x002E3120
static cell n_gfxShowLoadingIcon(AMX *, const cell *p) { Icons::showLoading(p[1] != 0); return 0; }   // 0x00325BE8
static cell n_gfxHideLoadingIcon(AMX *, const cell *) { Icons::hideLoading(); return 0; }       // 0x0032557C
static cell n_gfxShowHomeLockIcon(AMX *, const cell *) { Icons::showHomeLock(); return 0; }     // 0x00325BD8
static cell n_gfxChooseAdvice(AMX *, const cell *) { Icons::chooseAdvice(); return 0; }         // 0x00324F04

// 0x002F04E4: gfxTakeScreenshot(): both eyes of the top screen read back (TextureTGA) and handed to the
// save layer's thread (savedata.cpp, screenshot.cpp); false while a save is running.
static cell n_gfxTakeScreenshot(AMX *, const cell *)
{
	if (SaveData::busy())
		return 0;
	s_left->getFromFrameBuffer(s_leftBuffer, true);
	s_right->getFromFrameBuffer(s_rightBuffer, true);
	SaveData::takeScreenshot(s_left->data, s_right->data, s_left->width * s_left->height * 3 + 0x13,
	                         s_right->width * s_right->height * 3 + 0x13);
	return 1;
}

// ---- the developers' debug drawing -----------------------------------------------------------------------------

// 0x003255C4: gfxPrintStringf(x, y, format[], ...): into the debug console's text (2 KB, 50 columns:
// System::getDebugBuffer), drawn by nothing in the retail build. 0x00324FD4 gfxClearConsole empties it.
static cell n_gfxPrintStringf(AMX *, const cell *p);
static cell n_gfxClearConsole(AMX *, const cell *) { char *b = System::getDebugBuffer(); memset(b, 0, 0x808); return 0; }
// 0x003250D8: gfxDrawLine(from[3], to[3], colour[3]) (DebugFX); 0x00324FF8 gfxDebugClear; 0x00324540
// gfxAddMarker(position[3]): a red marker 10 units above, only with the world's show flag 4.
static cell n_gfxDrawLine(AMX *, const cell *p) { SELF; cell *c = self->getAddr(p[3], 0); DebugFX::drawLine(self->getVector3(p[1]), self->getVector3(p[2]), rgba(c[0], c[1], c[2], 255)); return 0; }
static cell n_gfxDebugClear(AMX *, const cell *) { DebugFX::clear(); return 0; }
static cell n_gfxAddMarker(AMX *, const cell *p);
// 0x0032558C: gfxLoadTexture(name[]): reads the name, loads nothing.
static cell n_gfxLoadTexture(AMX *, const cell *p) { SELF; char n[384]; n[0] = 0; self->getString(n, p[1]); return 0; }
