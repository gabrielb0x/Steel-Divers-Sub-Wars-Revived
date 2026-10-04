// source/main.cpp (main.o): the game's entry point and main loop.
//
// Reconstructed by hand from decomp/raw/source/main.cpp and the disassembly.
// Function names come from the linker map (romfs:/map); field names marked
// "unknown" or "probably" are not confirmed yet. Not compilable on its own.
// Left out: calls whose results only fed debug code stripped from the retail
// build (System::getMainMemAllocator(), System::getDeviceMemAllocator(), and a
// strncpy of the profiler label "total" into a 0x180-byte buffer).
//
// The game is a sequence of "modes", each one a Pawn script (romfs:/amx/mode_*.amx:
// mode_title, mode_select, mode_lobby, mode_periscope, mode_shop, ...). The
// running mode script picks the next one with amxSetModeScript() and finishes;
// nnMain then tears the mode down and loads the next one.

// 0x0050B41C: loader running the current mode script, built by __sti___8_main_cpp.
static ScriptAMXLoader s_modeLoader;
static u32 s_activeMask;    // 0x0050B640
static s32 s_unknown638;    // 0x0050B638, set to 10000 when a mode starts

// 0x00100114
extern "C" void nnMain()
{
	System::init();
	Graphics::init();
	Renderer::init(3);              // allocates the three renderers set up below
	RenderTargetMemory::init(0x80000);
	Layout::init();
	DataRouter::init();
	SyncList::init();
	SyncEvent::init();
	DebugFX::init();
	Fader::init();
	DOF::init();
	Distortion::init();
	SpeedBlur::init();
	EffectManager::init();
	FaceSystem::init();
	IME::init();
	ParticleManager::setupTimer();
	amxSysInit();
	Font::loadFonts("fonts/title-fonts.bxml");
	Font::loadFonts("fonts/main-fonts.bxml");
	System::setDeviceMemGroup(1);
	Graphics::freezeVRAM();

	amxSetModeScript("mode_title");
	Fader::startFade(1);

	for (;;) {
		// ---- Start a mode: reset everything the previous one owned ----
		System::resetHeaps();
		MemoryProfiler::resetAll(1);
		MemoryProfiler::resetAll(4);
		Graphics::reset();
		Resource::resetStock();
		ModelResource::resetStock();
		ModelSet::resetStock();
		MemBlock::resetStock();
		AMXLoader::resetStock();
		CollShape::resetStock();
		EffectManager::reset();
		InstanceSys::init();
		DOF::reset();
		Layout::reset();
		initAmxScratchBuffers();
		SyncList::clear();
		System::setPaused(false);
		System::getController()->reset();
		amxSysReset();
		s_modeLoader.init();

		// 0xA5F80 bytes, constructor inlined: CollisionScene at +0x418, ActorCacheData[0x41A0]
		// at +0x10444, then 0x14 objects of 0x194 bytes at +0xA3EC4. Never deleted:
		// System::resetHeaps() wipes the heap when the next mode starts.
		World *world = new World();
		world->init();

		// Renderer 0: top screen 3D scene (stereo), 1: top screen 2D/layouts,
		// 2: bottom screen. The trailing parameters are not identified yet.
		Renderer::getRenderer(0)->init(0, 400, 240, 1, 1, 1, 0, 0x82400, 0x80);
		Renderer::getRenderer(1)->init(1, 400, 240, 1, 0, 1, 1, 0x41200, 0x80);
		Renderer::getRenderer(2)->init(2, 320, 240, 0, 0, 0, 1, 0x82400, 0x80);
		Renderer::getRenderer(0)->addStereoCamera();
		Renderer::getRenderer(0)->addCausticCameras();

		Renderer *top2d = Renderer::getRenderer(1);
		top2d->unknownB8 = 0xFF000000;      // ARGB opaque black, probably the clear colour
		top2d->unknownBC = false;
		top2d->unknownBD = true;
		top2d->unknown1154 = false;
		top2d->add2DCamera();
		Scene::addDirLight(top2d->scene, "camlight", 0xFFFFFFFF, 0xFF000000, 0xFFFFFFFF);
		Renderer::getRenderer(2)->add2DCamera();
		WaitScreen::init();

		// The retail build patched the log call out (its arguments are still set up).
		// DEBUG_LOG(__FILE__, 336, "Entering Mode : %s\n", amxGetModeScript());
		s_activeMask = Renderer::getActiveMask();
		s_modeLoader.load(amxGetModeScript(), 0x800);
		s_unknown638 = 10000;
		for (int i = 0; i < 3; i++) {
			Renderer::getRenderer(i)->update();
		}
		EffectManager::initNWCallBacks();
		Icons::init();

		u8 frame = 0;   // wraps at s_unknown620 (0x0038E620); nothing reads it in the retail build
		for (;;) {
			// ---- Simulation ----
			u32 vblankAtStart = Graphics::getVBlankCount();
			amxSysSetGlobal("system.thisframetime", amx_ftoc(System::getRunningTimeInSeconds()));
			AMXProfiler::resetProfiles();

			if (Network::isActive()) {
				Network::recv();
			}
			Network::dispatch();
			System::update();

			// The scripts and the world are updated under the script mutex
			// (nn::os::Mutex::Lock/Unlock inlined: svc 0x24 / svc 0x14).
			nn::os::Mutex *scriptMutex = amxSysGetMutex(0);
			scriptMutex->Lock();
			VEC3 cameraPos = Renderer::getRenderer(0)->cameraPos;   // 3 floats at +0xC4, probably the camera
			world->update(&cameraPos);
			AMXLoader::runAll();
			if (s_modeLoader.isFinished()) {
				scriptMutex->Unlock();
				break;
			}
			amxOnlineUpdate();
			Network::update();
			if (s_modeLoader.isFinished()) {
				scriptMutex->Unlock();
				break;
			}

			if (Network::isActive()) {
				SyncList::removeOrphanedActors();
				SyncList::prime();
				DataRouter::dbgTotalsClear();
				Network::send();
				Network::recv();
			}
			Network::dispatch();
			if (Network::isActive()) {
				DataStreamer::dbgSentClear();
				Network::send();
				DataStreamer::update();
			}

			Icons::update();
			for (int i = 0; i < 3; i++) {
				Renderer::getRenderer(i)->preCullUpdate();
			}
			world->postScriptUpdate(&Renderer::getRenderer(0)->cameraPos);
			s_frameCounters = {};   // 0x0038E514 and 0x0038E528..0x0038E540, meaning unknown
			for (int i = 0; i < 3; i++) {
				Renderer::getRenderer(i)->update();
			}
			scriptMutex->Unlock();

			// ---- Rendering ----
			Fader::update();
			Graphics::getRenderContext()->ResetState();
			Renderer::getRenderer(0)->generateModelCmdList();
			Graphics::getRenderContext()->ResetState();
			Renderer::getRenderer(1)->generateLayoutCmdList();
			Renderer::getRenderer(0)->preDraw(1);
			Renderer::getRenderer(0)->preDraw(2);
			EffectManager::preDraw(Renderer::getRenderer(0), 1);
			EffectManager::preDraw(Renderer::getRenderer(0), 2);

			// Top screen, once per eye (1 = left, 2 = right); unrolled in the binary.
			Graphics::setViewport(0);
			for (int eye = 1; eye <= 2; eye++) {
				Renderer::getRenderer(0)->clear();
				Renderer::getRenderer(0)->drawModelsStereo(eye);
				Renderer::getRenderer(0)->drawEffects(eye);
				Graphics::updateFBTextures();
				Renderer::getRenderer(1)->clear();
				Graphics::getRenderContext()->ResetState();
				Renderer::getRenderer(1)->drawModels();
				Renderer::getRenderer(1)->drawLayoutsStereo(eye);
				DebugFX::draw(0);
				Fader::draw(1);
				Icons::drawStereo(Renderer::getRenderer(1), eye);
				Graphics::transferBuffer(eye - 1);
			}

			// Bottom screen.
			Graphics::setViewport(1);
			Renderer::getRenderer(2)->clear();
			Renderer::getRenderer(2)->drawLayouts();
			Fader::draw(0);
			Icons::draw(Renderer::getRenderer(2));
			Graphics::transferBuffer(2);

			if (++frame >= s_unknown620) {
				frame = 0;
			}
			Graphics::stopDraw();
			for (int i = 0; i < 3; i++) {
				Renderer::getRenderer(i)->updateDowntime();
			}
			FaceSystem::update();
			ParticleManager::cleanupUnused(Renderer::getRenderer(0)->scene->unknown209C);
			Graphics::flip(1);
			Graphics::runDraw();
			nn::os::Thread::Yield();    // svc SleepThread(0)

			// 30 fps: every frame lasts at least two VBlanks.
			u32 elapsed = Graphics::getVBlankCount() - vblankAtStart;
			if (elapsed == 0) {
				Graphics::waitVBlank();
				Graphics::waitVBlank();
			}
			else if (elapsed == 1) {
				Graphics::waitVBlank();
			}
			DebugFX::clear();
		}

		// ---- The mode script finished: tear the mode down ----
		Graphics::clearAll();
		s_modeLoader.cleanup();
		amx_EffectsCleanup();
		ModelSet::cleanupStock();
		ModelResource::cleanupStock();
		Renderer::cleanupAll();
		Graphics::cleanup();
		AMXLoader::cleanupAll();
		Fader::blackout();
	}
}

// 0x00319194: static initialiser of main.o.
static void __sti___8_main_cpp()
{
	s_unknown628 = -1;   // 0x0038E628
	s_unknown62C = -1;   // 0x0038E62C
	s_unknown630 = 0;    // 0x0038E630
	s_unknown634 = 0;    // 0x0038E634
	new (&s_modeLoader) ScriptAMXLoader();
}
