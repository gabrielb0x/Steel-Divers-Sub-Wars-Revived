// source/amx/amxeffects.cpp (amxeffects.o): the effect natives of the scripts (natives_Effects,
// amx_EffectsInit 0x00171CF0): bubbles, oil (the metaballs), dust, fish, the "fish tank" (the submarine seen
// in its tank in the menus), particles, distortion, depth of field, speed blur, torpedo trails, the
// fading of objects that hide the player, the light mask, the credits.
//
// Reconstructed by hand from decomp/raw/source/amx/amxeffects.cpp and the disassembly. Not compilable on its own.
//
// Each effect is created by its *Init native once per mode: a small Drawable (0x14 bytes, with the effect's
// own vtable) added to the first active renderer at a draw stage — bubbles 3, oil 2, dust 3, fish 2, fish
// tank 4, distortion 4, speed blur 4, torpedo trails 3, credits 4, object fade 1, light mask 11 (layer 0).
// amx_EffectsCleanup (0x00101348, when a mode ends) forgets them all.

static Drawable *s_bubbles, *s_oil, *s_lightMask, *s_fish, *s_dust, *s_fishTank, *s_trails, *s_distortion,
                *s_speedBlur;                     // 0x0038DCF8..0x0038DD20
static Credits *s_credits;                        // 0x0038DD14
static ObjectFade *s_objectFade;                  // 0x0038DD1C (0x135BC bytes)

template <typename Make> static void init(Drawable *&slot, int stage, Make make)
{
	if (slot != nullptr)
		return;
	slot = make();
	for (int i = 0; i < Renderer::getNumRenderers(); i++) {
		Renderer *r = Renderer::getRenderer(i);
		if (r->isActive()) {
			r->addDrawable(slot, 0, stage);
			return;
		}
	}
}

#define SELF AMXLoader *self = AMXLoader::getCurrentLoader()

// ---- bubbles (effects/bubbles.cpp) ---------------------------------------------------------------------
static cell n_fxBubbleInit(AMX *, const cell *) { init(s_bubbles, 3, [] { Bubbles::init(firstActiveRenderer()); return new BubbleDrawable(); }); return 0; }   // 0x0032307C
static cell n_fxBubbleReset(AMX *, const cell *) { Bubbles::reset(); return 0; }   // 0x00323148
// 0x00322E88: fxBubbleAdd(position[3], velocity[3]); 0x00322EE4: fxBubbleAddMultiple(count, position[3],
// spread[3], velocity[3]): each bubble placed and sped at random (7 random draws).
static cell n_fxBubbleAdd(AMX *, const cell *p) { SELF; Bubbles::addBubble(self->getVector3(p[1]), self->getVector3(p[2])); return 0; }
static cell n_fxBubbleAddMultiple(AMX *, const cell *p);

// ---- oil leaking from damaged subs (metaball.cpp) ------------------------------------------------------
static cell n_fxOilInit(AMX *, const cell *) { init(s_oil, 2, [] { return new MetaBallDrawable(); }); return 0; }   // 0x00323C64
static cell n_fxOilAdd(AMX *, const cell *p) { SELF; MetaBallSys::add(self->getVector3(p[1]), self->getVector3(p[2]), self->getVector3(p[3])); return 0; }   // 0x00323BF0
static cell n_fxOilAddMultiple(AMX *, const cell *) { return 0; }   // 0x00323C5C (empty)

// ---- dust, fish ----------------------------------------------------------------------------------------
static cell n_fxDustInit(AMX *, const cell *) { init(s_dust, 3, [] { return new DustDrawable(); }); return 0; }   // 0x003233BC
static cell n_fxDustEnableSpeedScale(AMX *, const cell *p) { if (s_dust) Dust::enableSpeedScale(p[1] != 0); return 0; }   // 0x0032338C
static cell n_fxFishInit(AMX *, const cell *p) { init(s_fish, 2, [p] { Fish::init(firstActiveRenderer(), p[1]); return new FishDrawable(); }); return 0; }   // 0x003234EC
static cell n_fxFishAvaliable(AMX *, const cell *) { return s_fish != nullptr; }   // 0x00323480 (the developers' spelling)
static cell n_fxFishAvoid(AMX *, const cell *p) { SELF; Fish::avoid(s_fish, self->getVector3(p[1]), self->getVector3(p[2])); return 0; }   // 0x00323498

// ---- the fish tank: the player's submarine in the menus (fishtankeffect.cpp) ------------------------------
// 0x003235C0: fxFishTankInit(actor): the effect on that actor, with the model "n2obj_refobj01".
static cell n_fxFishTankInit(AMX *, const cell *p);
static cell n_fxFishTankLocalPlayerDead(AMX *, const cell *);   // 0x003236C4: removed from the renderers, reset
static cell n_fxFishTankSetCustomColor(AMX *, const cell *p) { if (s_fishTank) FishTankEffect::setPlayerColour(p[1], rgba(p[2], p[3], p[4], p[5])); return 0; }   // 0x00323748
static cell n_fxFishTankSetCustomPattern(AMX *, const cell *p) { SELF; char s[384]; s[0] = 0; self->getString(s, p[1]); if (s_fishTank) FishTankEffect::setPlayerPattern(s); return 0; }   // 0x003237B8
static cell n_fxFishTankSetPlayerModel(AMX *, const cell *p) { SELF; char s[384]; s[0] = 0; self->getString(s, p[1]); if (s_fishTank) FishTankEffect::setPlayerName(s); return 0; }    // 0x00323808

// ---- particles (particle.cpp: the scene's ParticleManager, +0x209C) ------------------------------------------
// 0x00323D28: fxParticleAdd(name[], position[3], rotation[3], scale[3], flag1, flag2): an instance (pointer).
static cell n_fxParticleAdd(AMX *, const cell *p);
static cell n_fxParticleIsActive(AMX *, const cell *p) { return p[1] ? ((ParticleInstance *)p[1])->active : 0; }   // 0x00323E58 (+0x0A)
static cell n_fxParticleIsAlive(AMX *, const cell *p) { return p[1] ? ((ParticleInstance *)p[1])->active : 0; }    // 0x00323E68 (the same byte)
static cell n_fxParticlePlay(AMX *, const cell *p) { if (p[1]) ((ParticleInstance *)p[1])->play(); return 0; }     // 0x00323F2C
static cell n_fxParticleStop(AMX *, const cell *p) { if (p[1]) ((ParticleInstance *)p[1])->stop(); return 0; }     // 0x00324028
static cell n_fxParticleKill(AMX *, const cell *p) { if (p[1]) ((ParticleInstance *)p[1])->kill(); return 0; }     // 0x00323E78
static cell n_fxParticleUpdate(AMX *, const cell *p) { if (p[1]) ((ParticleInstance *)p[1])->update(); return 0; } // 0x00324040
static cell n_fxParticlePosition(AMX *, const cell *p) { SELF; if (p[1]) ((ParticleInstance *)p[1])->setPosition(self->getVector3(p[2])); return 0; }   // 0x00323F44
static cell n_fxParticleRotation(AMX *, const cell *p) { SELF; if (p[1]) ((ParticleInstance *)p[1])->setRotation(self->getVector3(p[2])); return 0; }   // 0x00323F84
static cell n_fxParticleScale(AMX *, const cell *p) { SELF; if (p[1]) ((ParticleInstance *)p[1])->setScale(self->getVector3(p[2])); return 0; }         // 0x00323FC4
static cell n_fxParticleSetParameters(AMX *, const cell *p) { if (p[1]) ((ParticleInstance *)p[1])->setEmitterParameters(amx_ctof(p[2]), amx_ctof(p[3])); return 0; }   // 0x00324004
static cell n_fxParticleKillAll(AMX *, const cell *p);   // 0x00323E90: every instance of a name

// ---- screen effects -------------------------------------------------------------------------------------------
static cell n_fxDistortionInit(AMX *, const cell *) { init(s_distortion, 4, [] { return new DistortionDrawable(); }); return 0; }   // 0x00323298
static cell n_fxDistortionSetEnabled(AMX *, const cell *p) { Distortion::setEnabled(p[1] != 0); return 0; }       // 0x0032335C
static cell n_fxDistortionSetStrength(AMX *, const cell *p) { Distortion::setBaseStrength(amx_ctof(p[1])); return 0; }   // 0x00323378
static cell n_fxDistortionEvent(AMX *, const cell *p) { Distortion::setTimedOverride(p[3] != 0, amx_ctof(p[1]), amx_ctof(p[2]), amx_ctof(p[4])); return 0; }   // 0x0032326C
static cell n_fxDOFSetStrength(AMX *, const cell *p) { DOF::setStrength(amx_ctof(p[1]), amx_ctof(p[2])); return 0; }               // 0x00323254
static cell n_fxSpeedBlurInit(AMX *, const cell *) { init(s_speedBlur, 4, [] { return new SpeedBlurDrawable(); }); return 0; }   // 0x00324070
static cell n_fxSpeedBlurEvent(AMX *, const cell *p) { SpeedBlur::trigger(amx_ctof(p[1]), amx_ctof(p[2])); return 0; }             // 0x00324058
static cell n_fxSpeedBlurStop(AMX *, const cell *) { SpeedBlur::stop(); return 0; }                                // 0x00324134
static cell n_fxSpeedBlurUseRipple(AMX *, const cell *p) { SpeedBlur::setAboveWater(p[1] == 0); return 0; }        // 0x00324144

// ---- torpedo trails (torpedotrail.cpp) -----------------------------------------------------------------------
static cell n_fxTorpedoTrailInit(AMX *, const cell *) { init(s_trails, 3, [] { TorpedoTrail::init(firstActiveRenderer()); return new TrailDrawable(); }); return 0; }   // 0x003241B0
static cell n_fxTorpedoTrailAddActor(AMX *, const cell *p) { SELF; if (s_trails) TorpedoTrail::add(self->getActor(p[1]), p[3] != 0); return 0; }      // 0x00324164
static cell n_fxTorpedoTrailRemoveActor(AMX *, const cell *p) { SELF; if (s_trails) TorpedoTrail::remove(self->getActor(p[1]), p[2] != 0); return 0; } // 0x00324280

// ---- objects fading out when they hide the player (effects/objectfade.cpp) -------------------------------------
static cell n_fxObjectFadeInit(AMX *, const cell *);                                     // 0x00323A64
#define FADE(call) SELF; if (s_objectFade) if (Actor *a = self->getActor(p[1])) s_objectFade->call; return 0
static cell n_fxObjectFadeRegisterActor(AMX *, const cell *p) { FADE(registerActor(a)); }        // 0x00323B48
static cell n_fxObjectFadeRemoveActor(AMX *, const cell *p) { FADE(deRegisterActor(a)); }        // 0x00323B84
static cell n_fxObjectFadeHideActor(AMX *, const cell *p) { FADE(hideActor(a)); }                // 0x00323A28
static cell n_fxObjectFadeFlash(AMX *, const cell *p) { FADE(triggerFlash(a)); }                 // 0x0032399C
static cell n_fxObjectFadeModelChange(AMX *, const cell *p) { FADE(modelSwitch(a)); }            // 0x00323B0C
static cell n_fxTriggerObjectFade(AMX *, const cell *p) { FADE(beginFade(a, p[3] != 0, amx_ctof(p[2]), amx_ctof(p[4]))); }   // 0x003242C8
static cell n_fxObjectFadeCancelAll(AMX *, const cell *) { if (s_objectFade) s_objectFade->cancelAll(); return 0; }    // 0x0032397C
static cell n_fxObjectFadeSetAlphaMode(AMX *, const cell *p) { if (s_objectFade) s_objectFade->setUseAlphaFade(p[1] != 0); return 0; }   // 0x00323BC0
// 0x003239E0: the actor's visibility (Float alpha), 1 without the effect.
static cell n_fxObjectFadeGetVis(AMX *, const cell *p);

// ---- light mask (lightmask.cpp) and credits (layouts/credits.cpp) ----------------------------------------------
static cell n_fxLightMaskInit(AMX *, const cell *);                                      // 0x00323858 (layer 11)
static cell n_fxLightMaskRegisterActor(AMX *, const cell *p) { SELF; LightMask::registerSub(s_lightMask, self->getActor(p[1])); return 0; }     // 0x0032391C
static cell n_fxLightMaskUnRegisterActor(AMX *, const cell *p) { SELF; LightMask::deRegisterSub(s_lightMask, self->getActor(p[1])); return 0; }  // 0x0032394C
// 0x00323198: the credits (0xEC bytes) made once, then only re-activated; 0x00323158 ends them.
static cell n_fxCreditsInit(AMX *, const cell *);
static cell n_fxCreditsEnd(AMX *, const cell *) { if (s_credits) { s_credits->finish(); s_credits->setActive(false); s_credits = nullptr; } return 0; }
