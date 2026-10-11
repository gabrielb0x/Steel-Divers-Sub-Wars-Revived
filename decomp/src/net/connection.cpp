// source/net/connection.cpp (connection.o): the base class of the two connections, ConnectionInternet
// (connectionInternet.cpp) and ConnectionLocal (connectionLocal.cpp, local wireless). It owns what both
// share: Pia's common and transport layers (one unreliable and one reliable protocol), sending and
// receiving the game's packets, starting Pia's session, and the waits behind the wait screen.
//
// Reconstructed by hand from decomp/raw/source/net/connection.cpp and the disassembly. Not compilable on its
// own. Network (network.cpp) holds the active connection and calls it through its vtable.

// The vtable (ConnectionInternet 0x003767CC, ConnectionLocal 0x0037660C; slots 0x38, 0x58, 0x5C were
// emptied by armlink, the Internet connection has no broadcast):
//   +0x00 init            +0x18 matchmakerLogin  +0x30 leaveSession          +0x48 broadcast (local)
//   +0x04 finalize        +0x1C scan             +0x34 getPID                +0x4C stopBroadcast (local)
//   +0x08 debug           +0x20 connect          +0x3C sendChangesToBlacklist +0x50 initPIATransport
//   +0x0C update          +0x24 send             +0x40 isInternet            +0x54 finalizePIATransport
//   +0x10 closeParticipation  +0x28 dispatch     +0x44 maxUnits (8 Internet)
//   +0x14 reopenParticipation +0x2C recv
class Connection {
public:
	u32 unreliable;                     // +0x04 handle of the unreliable protocol (Pia ProtocolManager)
	u32 reliable;                       // +0x08 handle of the reliable protocol
	u32 frame;                          // +0x0C counted by update(): the round robin of send()
};

// ---- module state (0x0038E638..0x0038E650) -------------------------------------------------------------
static u32 s_bufferFullCount;           // 0x0038E638 reliable sends refused in a row (buffer full)
static void *s_piaMemory;               // 0x0038E63C Pia's 4 MB, from the network heap
static nn::pia::util::NetworkErrorCodeConverter *s_errorConverter;  // 0x0038E640
static ConnectionLocal *s_local;        // 0x0038E644 the two connections, made once (local(), inet())
static ConnectionInternet *s_inet;      // 0x0038E648
static Receiver s_receiver;             // 0x0038E64C Network's NetReceiveCB

// 0x00175DB0 / 0x00175B20: the connection objects, made on first use in the network heap.
ConnectionLocal *Connection::local()
{
	if (s_local == nullptr) {
		ScopedHeap heap(System::getNetHeap());
		s_local = new ConnectionLocal();                // 16 bytes, vtable 0x0037660C
	}
	return s_local;
}

ConnectionInternet *Connection::inet()
{
	if (s_inet == nullptr) {
		ScopedHeap heap(System::getNetHeap());
		s_inet = new ConnectionInternet();              // 16 bytes, vtable 0x003767CC
	}
	return s_inet;
}

// 0x00175BA4: while connected, the HOME button and the sleep mode are off.
bool Connection::init()
{
	System::enableHomeButton(false);
	System::enableSleep(false);
	return true;
}

// 0x001761D0
void Connection::finalize()
{
	s_local = nullptr;
	s_inet = nullptr;
	System::enableHomeButton(true);
	System::enableSleep(true);
	s_receiver = nullptr;
}

void Connection::registerReceiver(Receiver receiver) { s_receiver = receiver; }   // 0x0017587C
void Connection::debug() {}                                                      // 0x00175DAC
u32 Connection::getPID() { return 0; }                                           // 0x00175E34
bool Connection::matchmakerLogin() { return true; }                              // 0x001755DC (local)
bool Connection::reopenParticipation() { return false; }                         // 0x0017588C (Internet)
void Connection::sendChangesToBlacklist() {}                                     // 0x00175964 (local)

// 0x00175E3C: every frame (Network::update): Pia's transport reports its errors here (Transport +0x38).
int Connection::update(bool)
{
	frame++;
	nn::pia::transport::Transport *transport = nn::pia::transport::Transport::s_pInstance;   // 0x003A3100
	if (transport != nullptr && transport->lastResult.IsFailure())
		return Network::getErrorCode(transport->lastResult);
	return 0;
}

// 0x001761AC: Pia's scheduler (both connections; the Internet one adds NEX's).
bool Connection::dispatch()
{
	if (nn::pia::common::Scheduler *scheduler = nn::pia::common::Scheduler::s_pInstance)   // 0x003A2F00
		scheduler->Dispatch(0);
	return true;
}

// ---- Pia: common layer (the scripts' netInit, through the connection's init) ----------------------------

// 0x00175E78: 4 MB for Pia, its scheduler and watermark manager, every trace on (the traces were compiled
// out of the retail Pia), and the converter of Pia's results to error codes. A failure of EndSetup stops
// the console (nndbgPanic).
bool Connection::initPIA()
{
	{
		ScopedHeap heap(System::getNetHeap());
		// "[Connection::initPIA] PIA pre-alloc NetHeap usage = %d", then "post-alloc"
		s_piaMemory = alloc(0x400000, 4);              // 0x002497C4
	}
	if (!Network::handleError(nn::pia::common::Initialize(s_piaMemory, 0x400000)))
		return false;
	if (!Network::handleError(nn::pia::common::BeginSetup()))
		return false;
	nn::pia::common::Trace::CreateInstance();
	nn::pia::common::Trace *trace = nn::pia::common::Trace::s_pInstance;      // 0x003A2F90
	trace->enabled = true;                                                      // +0x10
	trace->flags[0] = trace->flags[1] = 0xFFFFFFFF;
	if (!Network::handleError(nn::pia::common::Scheduler::CreateInstance(0x18)))
		return false;
	if (!Network::handleError(nn::pia::common::WatermarkManager::CreateInstance()))
		return false;
	{
		ScopedHeap heap(System::getNetHeap());
		// "[Connection::initPIA] NetworkErrorCodeConverter pre-alloc NetHeap usage = %d", then "post-alloc"
		s_errorConverter = new nn::pia::util::NetworkErrorCodeConverter();
	}
	if (!Network::handleError(nn::pia::common::EndSetup())) {
		nndbgPanic();
		return false;
	}
	if (nn::pia::common::WatermarkManager *watermarks = nn::pia::common::WatermarkManager::s_pInstance)
		watermarks->EnableAllWatermark();
	return true;
}

// 0x0017516C: the network heap is reset as a whole ("[Connection::finalizePIA] Pre-reset NetHeap usage =
// %d", then "Post-reset"): everything Pia, NEX and the connections allocated goes at once.
void Connection::finalizePIA()
{
	nn::pia::common::Finalize();
	s_errorConverter = nullptr;
	s_piaMemory = nullptr;
	System::getNetHeap().reset();
}

// 0x001753B8: the trace flags of Pia, all or the usual ones (Trace +0x00 |= 0x01010103, +0x04 |= 0x47).
void Connection::dbgSetVerbose(bool verbose)
{
	nn::pia::common::Trace *trace = nn::pia::common::Trace::s_pInstance;
	if (verbose) {
		trace->flags[0] = 0xFFFFFFFF;
		trace->flags[1] = 0xFFFFFFFF;
	} else {
		trace->flags[0] |= 0x01010103;
		trace->flags[1] |= 0x47;
	}
}

// ---- Pia: transport and session (vtable +0x50 / +0x54) --------------------------------------------------

// 0x001755E4: the transport for maxUnits() stations, an unreliable protocol (32 buffers) and a reliable one
// (64 send and 64 receive buffers), then Pia's session (Session::initPIASession).
bool Connection::initPIATransport(const void *settings)
{
	if (!Network::handleError(nn::pia::transport::Initialize()))
		return false;
	if (!Network::handleError(nn::pia::transport::BeginSetup()))
		return false;
	nn::pia::transport::Transport::Setting setting;
	setting.first = settings;
	setting.maxStations = maxUnits();                                           // vtable +0x44
	setting.value8 = 0x5B;
	setting.valueC = 0x103;
	setting.value10 = setting.value14 = 0;
	if (!Network::handleError(nn::pia::transport::Transport::CreateInstance(&setting)))
		return false;
	nn::pia::transport::ProtocolManager *protocols = &nn::pia::transport::Transport::s_pInstance->protocols;
	unreliable = protocols->CreateProtocol<nn::pia::transport::UnreliableProtocol>(0x2000);
	if (!Network::handleError(protocols->Search<nn::pia::transport::UnreliableProtocol>(unreliable)->Initialize(0x20)))
		return false;
	reliable = protocols->CreateProtocol<nn::pia::transport::ReliableProtocol>(0x3000);
	if (!Network::handleError(protocols->Search<nn::pia::transport::ReliableProtocol>(reliable)->Initialize(0x40, 0x40)))
		return false;
	if (!Network::handleError(nn::pia::transport::EndSetup()))
		return false;
	// "[Connection::initPIATransport] Pia current memory usage: %d"
	return Session::initPIASession((u32)settings);
}

// 0x00175894
void Connection::finalizePIATransport()
{
	Session::finalizePIASession();
	if (nn::pia::transport::Transport *transport = nn::pia::transport::Transport::s_pInstance) {
		if (ReliableProtocol *p = transport->protocols.Search(reliable)) {
			p->Finalize();
			transport->protocols.DestroyProtocol(reliable);
			reliable = 0;
		}
		if (UnreliableProtocol *p = transport->protocols.Search(unreliable)) {
			p->Finalize();
			transport->protocols.DestroyProtocol(unreliable);
			unreliable = 0;
		}
	}
	nn::pia::transport::Transport::DestroyInstance();
	nn::pia::transport::Finalize();
}

// 0x00175444: starts Pia's session with the game's signature key and the player's name. The key is a nod
// to the submarine film: Pia signs every packet with it, so only Sub Wars consoles understand each other.
bool Connection::startupSession()
{
	char key[24] = "thehuntforredoctober";                                   // 0x00175580, 21 bytes used
	nn::pia::common::SignatureSetting signature(1, key, 21);
	nn::pia::session::StationInfo me;
	wchar_t name[11];
	if (nn::friends::CTR::detail::GetMyScreenName(name).IsSuccess() && name[0] != 0) {
		for (me.nameLength = 0; me.nameLength < 11 && name[me.nameLength] != 0; me.nameLength++)
			me.name[me.nameLength] = name[me.nameLength];
	} else {
		wcscpy(me.name, L"DummyName");                                         // 0x00354198
		me.nameLength = 9;
	}
	me.flag = 0;
	return Network::handleError(nn::pia::session::Session::s_pInstance->Startup(10000, 500, &me, &signature, nullptr));
}

// ---- data ----------------------------------------------------------------------------------------------

// 0x00175968 (vtable +0x24): a reliable packet goes to its node (or everybody); an unreliable one goes
// round robin, to two other consoles per frame.
bool Connection::send(const void *data, u32 length, u32 node, bool isReliable)
{
	if (isReliable)
		return sendReliable(data, length, node);
	return sendUnreliableRoundRobin(2, data, length);
}

// 0x001752A4: "[Connection::sendReliableAll] Outgoing CRC = %x" (generateCRC, for the log). A full send
// buffer (0xD861482C) is not an error, unless it happens 30 times in a row: "[Connection::sendReliable]
// nn::pia::ResultBufferIsFull() was hit %d times in a row!", then handleError with it.
bool Connection::sendReliable(const void *data, u32 length, u32 node)
{
	ReliableProtocol *protocol = protocols()->Search(reliable);
	generateCRC(data, length);
	u8 station = Session::convertIdViteiToPia(node);
	if (station != 0xFF && protocol->stationSlot(station) == nullptr)           // 0x001EB3DC: not one of ours
		return true;
	nn::Result result = protocol->Send(station, data, length);
	if (result.IsSuccess())
		return true;
	if (result != 0xD861482C)                                                  // ResultBufferIsFull
		return Network::handleError(result);
	if (++s_bufferFullCount == 30) {
		Network::handleError(result);
		s_bufferFullCount = 0;
	}
	return false;
}

// 0x00175990: `count` sends this frame, each to the next console of the session in turn (slot
// (frame * count + i) % nodeCount, slot 0 standing for this console: skipped). With 8 players, each one
// gets this console's unreliable data (the synced actors) every 4 frames.
bool Connection::sendUnreliableRoundRobin(int count, const void *data, u32 length)
{
	bool ok = true;
	nn::pia::transport::StationManager *stations = nn::pia::transport::StationManager::s_pInstance;
	nn::pia::transport::Station *me = stations->localStation;                  // +0xA4
	for (int i = 0; i < count; i++) {
		int slot = (frame * count + i) % Session::getNodeCount();
		u8 target = 0xFD;                                                       // none
		int n = slot - 1;
		for (nn::pia::transport::Station *station : stations->stations)
			if (station->index != me->index && --n == -1)
				target = station->index;
		if (target == 0xFD)
			continue;
		nn::Result result = protocols()->Search(unreliable)->Send(target, data, length);
		if (result.IsFailure() && (result == 0xD861482C || !Network::handleError(result)))
			ok = false;
	}
	return ok;
}

// 0x00175BC0 (vtable +0x2C): everything received, unreliable first, then reliable (1,500 bytes at most
// per packet), each packet to the receiver with its sender's node id. Pia's "no data" (0xD1614828) and
// 0xD8A14884 end a protocol's loop normally; returns the error code of the last result.
int Connection::recv()
{
	u8 buffer[0x5DC];
	u8 station;
	u32 length;
	nn::Result result = 0xE7E3FFFF;
	if (unreliable != 0) {
		UnreliableProtocol *protocol = protocols()->Search(unreliable);
		while ((result = protocol->Receive(&station, buffer, &length, sizeof buffer)).IsSuccess())
			if (length != 0 && s_receiver != nullptr)
				s_receiver(Session::convertIdPiaToVitei(station), buffer, length);
		if (result != 0xD1614828 && result != 0xD8A14884) {
			Network::printResultError();
			return Network::getErrorCode(result);
		}
	}
	if (reliable != 0) {
		ReliableProtocol *protocol = protocols()->Search(reliable);
		while ((result = protocol->Receive(&station, buffer, &length, sizeof buffer)).IsSuccess()) {
			generateCRC(buffer, length);           // "[Connection::recv] Incoming CRC = %x, len = %d"
			if (length != 0 && s_receiver != nullptr)
				s_receiver(Session::convertIdPiaToVitei(station), buffer, length);
		}
		if (result != 0xD1614828 && result != 0xD8A14884) {
			Network::printResultError();
			return Network::getErrorCode(result);
		}
	}
	return Network::getErrorCode(result);
}

// ---- waits (the wait screen turns meanwhile) ------------------------------------------------------------

// 0x00213764: waits for a Pia job (CallContext: state 2 done, 3 failed, 4 cancelled). `dispatch`: run the
// connection meanwhile; `checkErrors`: stop on the connection's first error. 0: done and successful,
// 1: failed or cancelled, 2: stopped by an error (already handled).
int Connection::waitCallContext(nn::pia::common::CallContext *call, bool dispatchMeanwhile, bool checkErrors)
{
	int error = 0;
	if (call->state == 4) {
		WaitScreen::end();
		return 1;
	}
	while (call->state != 2 && call->state != 3 && call->state != 4) {
		if (dispatchMeanwhile) {
			dispatch();
			if (checkErrors && error == 0)
				error = update(false);
		}
		if (call->state == 2 || call->state == 3 || call->state == 4)
			break;
		if (dispatchMeanwhile)
			dispatch();
		WaitScreen::render();
	}
	WaitScreen::end();
	if (error != 0) {
		Network::handleError(error);
		return 2;
	}
	return call->state == 2 && call->result.IsSuccess() ? 0 : 1;
}

// 0x0021C048: the same for a NEX call (ProtocolCallContext: state +0x10, 1 while running, 2 done; its
// result at +0x38). An error of the connection cancels the call. The wait screen is optional.
int Connection::waitCallContext(nn::nex::ProtocolCallContext *call, bool dispatchMeanwhile, bool checkErrors,
                                bool showWaitScreen)
{
	int error = 0;
	while (call->state == 1) {
		if (dispatchMeanwhile) {
			dispatch();
			if (checkErrors && error == 0 && (error = update(false)) != 0)
				call->Cancel(4);
		}
		if (call->state != 1)
			break;
		if (dispatchMeanwhile)
			dispatch();
		if (showWaitScreen)
			WaitScreen::render();
	}
	if (showWaitScreen)
		WaitScreen::end();
	if (error != 0) {
		Network::handleError(error);
		return 2;
	}
	return call->state == 2 && call->result.IsSuccess() ? 0 : 1;
}

// 0x0021BDFC: waits for an nn::os event (svcWaitSynchronization1: at once, then 20 ms at a time).
// 0: signalled, 2: stopped by an error of the connection (already handled).
int Connection::waitEvent(nn::os::Event *event, bool dispatchMeanwhile, bool checkErrors)
{
	for (;;) {
		if (event->Wait(0))
			break;
		if (dispatchMeanwhile) {
			dispatch();
			if (checkErrors) {
				if (int error = update(false)) {
					WaitScreen::end();
					Network::handleError(error);
					return 2;
				}
			}
		}
		if (event->Wait(20 * 1000 * 1000))
			break;
		if (dispatchMeanwhile)
			dispatch();
		WaitScreen::render();
	}
	WaitScreen::end();
	return 0;
}
