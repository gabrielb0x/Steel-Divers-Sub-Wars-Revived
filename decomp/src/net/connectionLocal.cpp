// source/net/connectionLocal.cpp (connectionLocal.o): local wireless play (nn::uds, through Pia's "local"
// layer): one console opens a network ("broadcast"), the others scan for it and join; then a Pia session
// runs over it as over the Internet (session.cpp).
//
// Reconstructed by hand from decomp/raw/source/net/connectionLocal.cpp and the disassembly. Not compilable
// on its own. Pia's objects: nn::pia::local::UdsNode::s_pInstance (0x003A300C), UdsFacade::s_pInstance
// (0x003A2FD8).
//
// The network: sub id = the version checksum % 255 (so that only the same version meets, as online),
// 8 consoles, and the passphrase "BABBAGE_MATSURI" (16 bytes with its NUL), a name of the developers'.
// The UdsNode methods called through its vtable are named here after what they are given and do; the map
// has no names for them (their vtable offsets are given).

// ---- module state (0x0038E698..0x0038E6D4) -------------------------------------------------------------
static bool s_piaLocalReady;            // 0x0038E698 nn::pia::local initialised and its buffers allocated
static bool s_isHost;                   // 0x0038E699 broadcast (host) or connect (client)
static bool s_networkReady;             // 0x0038E69A the UDS link is up: the Pia session may start
static bool s_networkLost;              // 0x0038E69B leave at the next update
static bool s_debugError;               // 0x0038E69C debug(): the next update fails with 018-0306
static bool s_startupFailedOnce;        // 0x0038E69D
static u32 s_receiveBufferSize = 0x14000;   // 0x0038E6A0
static u32 s_nodeBufferSize = 0x800;        // 0x0038E6A4
static void *s_nodeBuffer;              // 0x0038E6A8
static void *s_receiveBuffer;           // 0x0038E6AC
static u8 s_linkLevel;                  // 0x0038E6B0 signal strength (0..3) while connected
static ConnectionLocal *s_connection;   // 0x0038E6B4 this connection (init)
static nn::Result s_lastStartup = 0xE7E3FFFF;   // 0x0038E6BC (built on first use, guard 0x0038E6B8)
static nn::os::Event s_scanIdle;        // 0x0038E6C0 signalled when no scan runs
static ScanResult *s_scanResults;       // 0x0038E6C4 the scripts' array (scan)
static nn::Result s_scanResult;         // 0x0038E6C8 the scan's result, reported by update
static nn::os::Thread s_scanThread;     // 0x0038E6CC

static const char PASSPHRASE[16] = "BABBAGE_MATSURI";

// 0x00180438: Pia's local layer (once: an 80 KB receive buffer aligned on 4 KB, a 2 KB node buffer, from
// the network heap), then the UDS node and the facade.
bool ConnectionLocal::init()
{
	s_scanIdle.Initialize(true);
	s_scanIdle.Signal();
	if (!Connection::init())
		return false;
	if (!s_piaLocalReady) {
		if (!Network::handleError(nn::pia::local::Initialize()))
			return false;
		ScopedHeap heap(System::getNetHeap());
		s_nodeBuffer = alloc(s_nodeBufferSize, 4);
		s_receiveBuffer = alloc(s_receiveBufferSize, 0x1000);
		s_piaLocalReady = true;
	}
	nn::pia::local::BeginSetup();
	nn::pia::local::UdsNode::Setting setting = {s_receiveBuffer, s_receiveBufferSize, s_nodeBuffer,
	                                            s_nodeBufferSize, 0x10103};
	if (!Network::handleError(nn::pia::local::UdsNode::CreateInstance(&setting)))
		return false;
	if (!Network::handleError(nn::pia::local::UdsNode::s_pInstance->Initialize(12)))     // vtable +0x08
		return false;
	if (!Network::handleError(nn::pia::local::UdsFacade::CreateInstance()))
		return false;
	nn::pia::local::EndSetup();
	s_connection = this;
	return true;
}

// 0x00180B34: waits for a scan still running, then takes everything down. Pia's common layer is started
// again at once (finalizePIA + initPIA): the menus keep it.
void ConnectionLocal::finalize()
{
	ScopedHeap heap(System::getNetHeap());
	if (!s_scanIdle.Wait(0))
		waitEvent(&s_scanIdle, false, true);
	s_scanIdle.Finalize();
	nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance;
	checkError(node->lastError);                                       // "[ConnectionLocal::checkError] success = %d"
	nn::pia::local::UdsFacade::DestroyInstance();
	checkError(node->lastError);
	node->Finalize();                                                   // vtable +0x0C
	checkError(node->lastError);
	nn::pia::local::UdsNode::DestroyInstance();
	nn::pia::local::Finalize();
	s_piaLocalReady = false;
	Connection::finalize();
	Connection::finalizePIA();
	Connection::initPIA();
}

int ConnectionLocal::maxUnits() { return 8; }          // 0x00180D10
bool ConnectionLocal::isInternet() { return false; }   // 0x001801C0
void ConnectionLocal::debug() { s_debugError = true; } // 0x00180734 (a test of the error path)
bool ConnectionLocal::stopBroadcast() { return true; } // 0x0018035C

// 0x001803DC / 0x0018040C: Session::setParticipation.
bool ConnectionLocal::closeParticipation()
{
	if (nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance)
		node->Close(0);                                                 // vtable +0x28
	return true;
}

bool ConnectionLocal::reopenParticipation()
{
	if (nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance)
		node->Reopen();                                                 // vtable +0x2C
	return true;
}

// ---- host and client -----------------------------------------------------------------------------------

// 0x00180D18 (vtable +0x48): this console opens the network (8 consoles, channel 11) and hosts.
bool ConnectionLocal::broadcast()
{
	Network::setStatus(JOINING_SESSION);
	nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance;
	u32 id = node->CreateLocalCommunicationId(System::getNetworkId(), 0);
	node->RegisterUpdateEventCallback(udsUpdateEventCB, 0);
	if (!Network::handleError(node->CreateNetwork(System::getVersionChecksum() % 0xFF, 8, id, PASSPHRASE,
	                                              sizeof PASSPHRASE, 11, 0, 0)))  // vtable +0x10
		return false;
	s_isHost = true;
	Network::setStatus(IN_SESSION);
	return true;
}

// 0x001808B0 (vtable +0x20): joins the network of the console whose address (6 bytes) the player chose
// in the scan's list. Not found: error 0xD8A14825.
bool ConnectionLocal::connect(const u8 bssid[6])
{
	Network::setStatus(JOINING_SESSION);
	nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance;
	node->CreateLocalCommunicationId(System::getNetworkId(), 0);
	if (!Network::handleError(node->Scan(System::getVersionChecksum() % 0xFF)))          // vtable +0x30
		return false;
	static nn::uds::NetworkDescription found[16];                       // 0x108 bytes each
	u32 count;
	node->GetGatheringList(found, &count, 16);
	// "Start connect scan.  %d possibilities"
	for (u32 i = 0; i < count; i++) {
		if (memcmp(found[i].bssid, bssid, 6) != 0)
			continue;
		node->RegisterUpdateEventCallback(udsUpdateEventCB, 0);
		if (!Network::handleError(node->ConnectNetwork(&found[i], PASSPHRASE, sizeof PASSPHRASE)))  // +0x18
			return false;
		s_isHost = false;
		Network::setStatus(IN_SESSION);
		return true;
	}
	return Network::handleError(0xD8A14825);
}

// 0x001801C8 (vtable +0x30): the session, the facade, the transport, then the host destroys the network
// (node state 1, vtable +0x14) or a client leaves it (state 2 and more, vtable +0x1C).
bool ConnectionLocal::leaveSession()
{
	Network::setStatus(LEAVING_SESSION);
	ScopedHeap heap(System::getNetHeap());
	s_networkReady = false;
	bool ok = Session::finalize();
	nn::pia::local::UdsFacade::s_pInstance->Cleanup();                  // vtable +0x04
	finalizePIATransport();                                             // vtable +0x54
	nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance;
	if (node->state == 1)                                               // +0x04
		ok = Network::handleError(node->DestroyNetwork());
	else if (node->state > 1)
		ok = Network::handleError(node->DisconnectNetwork());
	Network::setStatus(DISCONNECTED);
	return ok;
}

// ---- every frame ---------------------------------------------------------------------------------------

// 0x00180748 (vtable +0x0C): errors of the scan and of the UDS node, then: a lost network is left, a ready
// one gets its Pia session (when `startSession`).
int ConnectionLocal::update(bool startSession)
{
	if (s_scanResult.IsFailure()) {
		int code = Network::getErrorCode(s_scanResult);
		s_scanResult = 0;
		return code;
	}
	if (nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance) {
		if (node->lastError.IsFailure())                                // +0x1140
			return Network::getErrorCode(node->lastError);
		node->ProcessUds();
		nn::Result processed = node->lastProcessError;                   // +0x2A50
		if (s_debugError || processed.IsFailure()) {
			node->ClearLastUdsNodeProcessError();
			int code = Network::getErrorCode(processed);
			if (s_debugError) {
				code = 180306;
				s_debugError = false;
			}
			return code;
		}
	}
	if (s_networkLost) {
		leaveSession();
		s_networkLost = false;
	} else if (startSession && !Session::isActive() && s_networkReady) {
		udsInitSession();
	}
	return Connection::update(true);
}

// 0x00172968 (UDS callback): the link's state. Connected (status 0, 6 or 9): its level, and the session
// may start. Anything else: a client leaves ("Disconnect! Reason = %d"), the network is lost. Event 3 is
// ignored.
static void udsUpdateEventCB(int event)
{
	if (event == 3)
		return;
	nn::uds::ConnectionStatus status;
	if (nn::pia::local::UdsNode::s_pInstance->GetConnectionStatus(&status).IsFailure())
		return;
	if (status.state == 0 || status.state == 6 || status.state == 9) {
		u8 level;
		nn::pia::local::UdsNode::s_pInstance->GetLinkLevel(&level);
		s_linkLevel = level;
		s_networkReady = true;
		return;
	}
	if (!s_isHost)
		nn::pia::local::UdsNode::s_pInstance->DisconnectNetwork();     // vtable +0x1C
	s_linkLevel = 0;
	s_networkLost = true;
}

// 0x00171A34: the transport over UDS (initPIATransport with Pia's UDS network factory), the facade's
// startup, then the session: created by the host, joined by a client (the host is UDS node 1).
// A failed startup is handled twice (once by an inlined checkError), then the first failure waits for the
// next frame; the same failure again is let through.
static bool udsInitSession()
{
	nn::pia::local::UdsNetworkFactory factory;
	if (!s_connection->initPIATransport(&factory))                      // vtable +0x50
		return false;
	nn::Result result = nn::pia::local::UdsFacade::s_pInstance->Startup();   // vtable +0x00
	Network::handleError(result);
	if (s_startupFailedOnce && result != s_lastStartup)
		s_startupFailedOnce = false;
	s_lastStartup = result;
	if (Network::handleError(result)) {
		s_startupFailedOnce = false;
	} else if (!s_startupFailedOnce) {
		s_startupFailedOnce = true;
		return false;
	}
	if (!Session::init())
		return false;
	bool ok;
	if (s_isHost) {
		ok = Session::create();
	} else {
		nn::pia::transport::StationConnectionInfo host;
		u32 master = nn::pia::local::UdsNode::s_pInstance->ConvertUdsNodeIdToTransportNodeId(1);
		// "Converted!  masterTransportNodeId == %d"
		ok = Network::handleError(nn::pia::local::UdsFacade::s_pInstance
		                              ->ConvertTransportNodeIdToStationConnectionInfo(master, &host))
		     && Session::join(&host);
	}
	if (!ok)
		return false;
	Session::setReady(true);
	return true;
}

// ---- scanning (the list of networks around, for the scripts) -------------------------------------------

struct ScanResult {                     // 0xD8 bytes per network, in the scripts' array
	u32 sessionId;                      // +0x00 (big-endian in the beacon)
	u8 id[24];                          // +0x04 the beacon's identification, the host's address first
	u8 applicationData[0xC8];           // +0x1C
	u32 applicationDataSize;            // +0xD4 0: not listed
};

// 0x00180664 (vtable +0x1C): unless a scan runs, starts one in a thread (priority 0x14, 4 KB stack).
void ConnectionLocal::scan(ScanResult *results, u32 max)
{
	if (!s_scanIdle.Wait(0))
		return;
	s_scanIdle.ClearSignal();
	s_scanResults = results;
	s_scanThread.TryStartUsingAutoStack(connectionLocalScanThread, max, 0x1000, 0x14);
}

// 0x00174BFC
static void connectionLocalScanThread(u32 max)
{
	connectionLocalScan(max);
	s_scanIdle.Signal();
	s_scanThread.Finalize();
}

// 0x001734E8: the networks of the same version with application data and without flag 0x200 (a byte of
// the beacon's attributes; full or closed), except an address kept at 0x0052E5B2; the scripts read
// "local.scanstatus.*".
static void connectionLocalScan(u32 max)
{
	nn::pia::local::UdsNode *node = nn::pia::local::UdsNode::s_pInstance;
	node->CreateLocalCommunicationId(System::getNetworkId(), 0);
	u32 listed = 0;
	s_scanResult = node->Scan(System::getVersionChecksum() % 0xFF);
	if (s_scanResult.IsSuccess()) {
		nn::uds::NetworkDescription found[16];
		u32 count;
		node->GetGatheringList(found, &count, 16);
		for (u32 i = 0; i < count; i++) {
			if (!found[i].flag08 || (found[i].attributes & 0x200) || listed >= max)
				continue;
			ScanResult &r = s_scanResults[listed];
			memcpy(r.id, found[i].id, 24);
			if (memcmp(r.id, (u8 *)0x0052E5B2, 6) == 0)
				continue;
			r.sessionId = found[i].flag08 ? byteswap(found[i].sessionId) : 0;
			memset(r.applicationData, 0, 0xB8);
			node->GetApplicationData(r.applicationData, &r.applicationDataSize, 200, &found[i]);   // +0x34
			if (r.applicationDataSize != 0)
				listed++;          // "[ConnectionLocal::connectionLocalScan] pGatheringArray[%d].Bssid = %s, ..."
		}
	}
	amxSysSetGlobal("local.scanstatus.isScanning", 0);
	amxSysSetGlobal("local.scanstatus.numNetworks", listed);
	amxSysSetGlobal("local.scanstatus.doneRefresh", 1);
}
