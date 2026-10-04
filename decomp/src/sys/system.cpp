// source/sys/system.cpp (system.o): start-up, heaps, time, HOME/power buttons, controller.
//
// Reconstructed by hand from decomp/raw/source/sys/system.cpp and the disassembly. Not compilable
// on its own. Globals are named after their use; addresses are given for each.
// Left out: the applet callbacks (myReceiveAwakeNotification, myReceiveSleepQueryNotification,
// pwrBtnCb), the parental-control (COPPA) helpers, showKeyboard, showEULAConfirm, getContinent and
// the date getters, which are thin wrappers of the SDK.

// ---- state (0x0038EB98..0x0038EC24) ----
static bool s_homeButtonEnabled;     // 0x0038EB98
static bool s_sleepEnabled;          // 0x0038EB99
static bool s_saving;                // 0x0038EB9A: HOME and power buttons wait while saving
static bool s_fakePowerButton;       // 0x0038EB9B (setFakePushPowerButton)
static bool s_startLcd;              // 0x0038EB9C: turn the screens on at the first update
static bool s_paused;                // 0x0038EB9E
static bool s_restrictPhotoExchange; // 0x0038EB9F
static bool s_soundReady;            // 0x0038EBA2
static BXML::Node *s_settings;       // 0x0038EBA4: <JP>, <US> or <EU> of bxml/settings.bxml
static u32 s_uniqueId;               // 0x0038EBA8: 3452 JP, 3453 US, 3454 EU (the title id 000D7Cxx..)
static u32 s_networkId;              // 0x0038EBAC: 3452 everywhere: all regions play together
static u32 s_frame;                  // 0x0038EBB0: frames since start-up (sysGetFrameNum)
static const char *s_revision;       // 0x0038EBE0: "31308" in v0 (bxml/buildinfo.bxml)
static s64 s_startTick;              // 0x0038EBE8: moved forward by the time spent in the HOME menu
static s64 s_initTick;               // 0x0038EBF0
static nn::os::LightEvent s_sleepEvent;   // 0x0038EBF8

// Heaps: an allocator and a group number; resetHeaps() frees groups 1 (main) and the device group.
struct Heap { Allocator *allocator; int group; };
static Heap s_currentHeap;           // 0x0038EC00
static Heap s_mainHeap;              // 0x0038EC08: main memory, group 1 (freed between modes)
static Heap s_sysHeap;               // 0x0038EC10: main memory, group 0 (kept)
static Heap s_netHeap;               // 0x0038EC18: main memory, group 2
static Heap s_deviceHeap;            // 0x0038EC20: device memory (graphics), group set by setDeviceMemGroup

static Allocator s_mainMemory;       // 0x005B669C: 24 MB
static Allocator s_deviceMemory;     // 0x005B8570: 32 MB
static Controller s_controller;      // 0x005BA444
static nn::os::MemoryBlock s_memoryBlock;   // 0x005CE4A4
extern DsSubAudioMgr g_audio;        // 0x005CE4B8

// 0x00100F84: SDK start-up hook, before nnMain: 32 MB of device memory, the rest as heap.
extern "C" void nninitStartUp()
{
	u32 heapSize = nn::os::GetAppMemorySize() - nn::os::GetUsingMemorySize() - 0x2000000;
	nn::os::SetupHeapForMemoryBlock(heapSize);
	if (nn::os::SetDeviceMemorySize(0x2000000).IsFailure()) {
		nndbgPanic();
	}
	nn::init::InitializeAllocator(0x80000);
	nn::os::ManagedThread::InitializeEnvironment();
}

// 0x001037A0: first call of nnMain.
void System::init()
{
	s_initTick = nn::os::Tick::GetSystemCurrent() - s_startTick;
	nn::applet::SetPowerButtonCallback(pwrBtnCb, 0);
	nn::fs::InitializeLatencyEmulation();
	s_sleepEnabled = true;
	nn::applet::EnableSleep(true);
	s_homeButtonEnabled = true;
	nn::applet::ClearHomeButtonState();
	nn::applet::SetSleepQueryCallback(myReceiveSleepQueryNotification, 0);
	nn::applet::SetAwakeCallback(myReceiveAwakeNotification, 0);
	s_sleepEvent.Initialize(false);
	nn::applet::Enable(true);
	if (nn::applet::GetOrderToCloseState() || nn::applet::IsReceivedWakeupByCancel()) {
		closeApplication();   // inlined each time: FaceSystem::exit, PrepareToClose, CloseApplication
	}

	nn::ndm::Initialize();
	nn::ndm::SuspendDaemons(6);   // StreetPass and friends daemons paused while the game runs
	nn::cfg::Initialize();
	nn::ubl::Initialize();
	nn::cfg::GetRegionCodeA3(nn::cfg::GetRegion());
	nn::cfg::GetLanguageCodeA2(nn::cfg::GetLanguage());

	s_memoryBlock.Initialize(0x1800000);
	s_mainMemory.init(s_memoryBlock.GetAddress(), s_memoryBlock.GetSize(), "MainMemory");
	s_deviceMemory.init(nn::os::GetDeviceMemoryAddress(), nn::os::GetDeviceMemorySize(), "DeviceMemory");
	s_sysHeap = { &s_mainMemory, 0 };
	s_mainHeap = { &s_mainMemory, 1 };
	s_netHeap = { &s_mainMemory, 2 };
	s_deviceHeap = { &s_deviceMemory, 0 };
	s_currentHeap = { &s_mainMemory, 0 };

	// Save data allocator, file system, RomFS.
	g_saveAllocator = new AllocatorHybrid(&s_deviceMemory);    // 0x0038EBD0
	nn::fs::Initialize();
	nn::friends::Initialize();
	size_t romSize = nn::fs::GetRomRequiredMemorySize(0x100, 0x10, true);
	nn::fs::MountRom("rom:", 0x100, 0x10, s_currentHeap.allocator->alloc(romSize, 4), romSize, true);
	Resource::resetStock();
	srand(0x12345678);    // C library: additive generator of 55 words, also used by System::random
	exceptionRegisterHandler();
	s_controller.init();

	// Region settings: ids used by the network code and the screenshots.
	BXML settings;
	settings.load("bxml/settings.bxml", 0);
	static const char *regions[] = { "JP", "US", "EU" };
	u32 region = nn::cfg::GetRegion();
	s_settings = settings.findNode(region < 3 ? regions[region] : "XX");
	s_uniqueId = s_settings->findAttribute("UniqueId")->asInt();
	s_networkId = s_settings->findAttribute("NetworkId")->asInt();

	// Sound: 4 MB of device memory.
	g_soundHeap = s_deviceMemory.alloc(0x400000, 0x80);       // 0x0038EBD4
	if (g_soundReinit) {                                       // 0x0038EBC8
		if (s_soundReady) {
			g_audio.finalize();
			while (!g_audio.IsFinalized()) {
				g_audio.CalcSceneInit();
				Graphics::waitVBlank();
			}
		}
		g_audio.Trg_InitCore(0);
		g_audio.Trg_SoundResourceSet(0);
		g_audio.setupHeap(g_soundHeap, 0x400000);
		g_audio.initialize();
		g_audio.Trg_Init();
		g_audio.Trg_CalcStart();
		s_soundReady = true;
		g_soundReinit = false;
	}

	DataStreamer::init();
	amxOnlineSubsystemInit();
	g_debugText = (u16 *)s_currentHeap.allocator->allocAligned(0x1000, 0x1000);   // 0x0038EBD8
	g_debugText[0] = 0;
	g_unknownEBDC = s_currentHeap.allocator->alloc(1, 4);

	// Build revision, shown on the title screen and hashed for the matchmaking (getVersionChecksum).
	if (Resource::fileExists("bxml/buildinfo.bxml")) {
		BXML buildinfo;
		buildinfo.initFromData(Resource::getData(Resource::getResource("bxml/buildinfo.bxml")));
		if (BXML::Node *revision = buildinfo.findNode("revision")) {
			if (BXML::Attribute *id = revision->findAttribute("id")) {
				s_revision = id->string();
			}
		}
	}
	SaveData::init(g_saveAllocator);
	Credits::initLoaders();
	s_restrictPhotoExchange = nn::cfg::IsRestrictPhotoExchange();
}

// 0x00103F40: once per frame, before the scripts (nnMain).
void System::update()
{
	if (s_startLcd) {
		nngxWaitVSync(0x402);
		nngxWaitVSync(0x402);
		nngxStartLcdDisplay();
		s_startLcd = false;
	}

	// Power button: handled at once unless the game is saving.
	if (s_fakePowerButton || nn::applet::GetPowerButtonState()) {
		if (!s_saving) {
			s_fakePowerButton = false;
			nn::applet::ProcessPowerButtonAndWait();
			if (nn::applet::GetOrderToCloseState() || nn::applet::IsReceivedWakeupByCancel()) {
				closeApplication();
			}
			nngxUpdateState(0x3FFF);
		}
	}

	// HOME button and sleep requests, after the first 5 frames.
	if (s_frame > 5 && !Icons::isHomeLockShowing() && !s_saving) {
		if (!s_homeButtonEnabled) {
			Icons::showHomeLock();   // the "HOME Menu cannot be displayed" icon
			if (nn::applet::GetOrderToCloseState() || nn::applet::IsReceivedWakeupByCancel()) {
				closeApplication();
			}
		} else {
			if (nn::applet::IsExpectedToReplySleepQuery()) {
				nn::applet::ReplySleepQuery(1);
				s_sleepEvent.Wait();          // log: "Applet: sleep later end"
			}
			if (nn::applet::IsExpectedToProcessHomeButton() && !Icons::isHomeLockShowing()) {
				s64 before = nn::os::Tick::GetSystemCurrent();
				nngxSplitDrawCmdlist();
				nngxWaitCmdlistDone();
				nn::applet::ProcessHomeButtonAndWait();
				if (nn::applet::GetOrderToCloseState() || nn::applet::IsReceivedWakeupByCancel()) {
					closeApplication();
				}
				nngxUpdateState(0x3FFF);
				// The time spent in the HOME Menu does not count (getRunningTimeInSeconds).
				s_startTick += nn::os::Tick::GetSystemCurrent() - before;
			}
			if (nn::applet::GetOrderToCloseState() || nn::applet::IsReceivedWakeupByCancel()) {
				g_audio.finalizeRequest();
				closeApplication();
			}
		}
	}

	s_controller.read();
	g_audio.CalcUpdate();
	s_frame++;
}

// 0x00103758: seconds since System::init, HOME Menu excluded ("system.thisframetime").
f32 System::getRunningTimeInSeconds()
{
	s64 ticks = nn::os::Tick::GetSystemCurrent() - s_startTick - s_initTick;
	return (f32)nn::os::Tick(ticks).ToSeconds();   // 268 111 856 ticks per second
}

// 0x00123C80
s64 System::getTime()
{
	return nn::os::Tick::GetSystemCurrent() - s_startTick;
}

// 0x00103708: when a mode starts: frees everything the previous mode allocated.
void System::resetHeaps()
{
	s_deviceHeap.allocator->freeGroup(s_deviceHeap.group);
	s_mainHeap.allocator->freeGroup(s_mainHeap.group);
	s_currentHeap = s_mainHeap;
	s_mainHeap.allocator->setGroup(s_mainHeap.group);
}

// 0x002524FC: makes `heap` the current one, returns the previous.
Heap System::useHeap(Heap heap)
{
	Heap previous = s_currentHeap;
	s_currentHeap = heap;
	heap.allocator->group = heap.group;    // Allocator +0x7C
	return previous;
}

Heap System::getSysHeap() { return s_sysHeap; }          // 0x0025253C
Heap System::getDeviceHeap() { return s_deviceHeap; }    // 0x002524E8
Heap System::getNetHeap() { return s_netHeap; }          // 0x0021C30C
void System::setDeviceMemGroup(int group) { s_deviceHeap.group = group; }   // 0x002540E4
Allocator *System::getMainMemAllocator() { return &s_mainMemory; }          // 0x0025402C
Allocator *System::getDeviceMemAllocator() { return &s_deviceMemory; }      // 0x002540F4
Controller *System::getController() { return &s_controller; }              // 0x00254020

// 0x001043E4 / 0x0024DE04: sysSetPaused / sysIsPaused. While paused, only the scripts with
// ignorePause run, the world does not move and the replay is not recorded.
void System::setPaused(bool paused) { s_paused = paused; }
bool System::isPaused() { return s_paused; }

u32 System::getGameFrameNum() { return s_frame; }        // 0x0010D1DC
u32 System::getUniqueId() { return s_uniqueId; }         // 0x00219144
u32 System::getNetworkId() { return s_networkId; }       // 0x0021BB44
const char *System::getVersionText() { return s_revision; }               // 0x002ECE2C
u32 System::getVersionChecksum() { return generateCRC(s_revision); }      // 0x0021BB34: CRC-32
bool System::isSleepEnabled() { return s_sleepEnabled; }                  // 0x002ECE54
bool System::isHomeButtonEnabled() { return s_homeButtonEnabled; }        // 0x002ECFF0
bool System::isRestrictPhotoExchange() { return s_restrictPhotoExchange; } // 0x002ED018
void System::setSaving(bool saving) { s_saving = saving; }               // 0x002ED334
void System::setFakePushPowerButton() { s_fakePowerButton = true; }       // 0x002ED000

// 0x0021A8B0
void System::enableSleep(bool enable)
{
	s_sleepEnabled = enable;
	nn::applet::EnableSleep(enable);
}

// 0x002436D0: random number in [0, max).
u32 System::random(u32 max)
{
	return rand() % max;
}
