// source/net/session.cpp (session.o): the game's view of a Pia session, the same for both connections
// (Internet and local wireless): who is in it (the "nodes"), what happened to them (joined, left, a new
// host), the session's clock, and how it failed.
//
// Reconstructed by hand from decomp/raw/source/net/session.cpp and the disassembly. Not compilable on its
// own. Pia's session object is nn::pia::session::Session::s_pInstance (0x003A3088, "No instance! %s: %d"
// when missing); its station manager is nn::pia::transport::StationManager::s_pInstance (0x003A30E8).
//
// Node ids. The developers' own ids (they wrote "vitei" ids, after their studio: convertIdViteiToPia,
// "viteiEventCode", "viteiNodeID" in the logs) are Pia's station index + 0xC00001, and 0xFFFF for Pia's
// 0xFF (no station). The scripts see these ids (netGetNodeID, the senders of netCallPublic...).

static inline u32 convertIdPiaToVitei(u8 station) { return station == 0xFF ? 0xFFFF : station + 0xC00001; }

// ---- module state (0x0038E7C0..0x0038E800, .data; 0x0056F600.., .bss) ----------------------------------
static bool s_ready;                    // 0x0038E7C0 in a session (setReady, by the connection that made it)
static bool s_nodesChanged;             // 0x0038E7C1 a station joined: count the nodes again
static bool s_linkFailure;              // 0x0038E7C2 set by Network::handleError (link lost)
static bool s_failureFlag3;             // 0x0038E7C3 cleared with every custom failure, read by nothing
static bool sIsParticipationAllowed;    // 0x0038E7C4 (its name in setParticipation's log)
static bool s_eventsOverflowed;         // 0x0038E7C5 more than 80 events waiting: error 16 next update
static u32 s_nodeCount;                 // 0x0038E7C8 nodes in the session, this console included
static int s_customFailure;             // 0x0038E7CC setCustomFailure: what the scripts show (netGetLastCustomFailure)
static u32 s_notifyCount;               // 0x0038E7D0
static u32 s_dataRegistered;            // 0x0038E7D4 the scripts' netSetDataRegistered...
static u32 s_subRegistered;             // 0x0038E7D8 ...netSetSubRegistered...
static u32 s_teamRegistered;            // 0x0038E7DC ...and netSetTeamRegistered: stored, read by nothing
static u16 s_stationCount;              // 0x0038E7E0 joins minus leaves seen by SessionEventCB
static u64 s_sessionTime;               // 0x0038E7E8 last value of the Pia session's clock

static u32 s_nodes[32];                 // 0x0056F600 node ids, sorted, s_nodeCount used
static u32 s_removedNodes[32];          // 0x0056F680 nodes that left, kept out until the next refresh
static SessionNotifyCB s_notify[10];    // 0x0056F700 registerNotifyCB: amxnet, DataStreamer, SyncEvent

// Pia's session events, queued by its callback (Pia's thread) and handled by update (the game's).
struct SessionEventData {               // 0x001831B4: the constructor clears `pending`
	bool pending;
	u8 event;                           // Pia's: 0 a station joined, 1 one left, 2 the host changed, 3 ?
	u8 station;
};
static SessionEventData s_events[80];   // 0x0056F728

// What the notify callbacks receive (the "viteiEventCode"): 0 the node count changed (updateNodeCount),
// 1 a node joined, 2 a node left, 3 the host changed, 4 Pia's event 3, 5 an unknown event.

// ---- Pia's callbacks -----------------------------------------------------------------------------------

// 0x00171980 (Session +0x34): keeps the event for the next update.
static void SessionEventCB(int event, u8 station)
{
	for (SessionEventData &e : s_events) {
		if (!e.pending) {
			e.event = event;
			e.station = station;
			e.pending = true;
			if (event == 1)
				s_stationCount--;
			else if (event == 0)
				s_stationCount++;
			return;
		}
	}
	s_eventsOverflowed = true;
}

// 0x00172CD4 (Session +0x38): may a console join? "Approval Callback: %s".
static bool sessionApprovalCB() { return sIsParticipationAllowed; }

// ---- every frame (Network::update) ---------------------------------------------------------------------

// 0x0011021C: hands the queued events to the notify callbacks, once Pia's own station count agrees with
// the joins and leaves received (Session +0x48), so that no event is handled before the ones it follows.
static void handleDueEvents()
{
	if (s_eventsOverflowed) {
		s_eventsOverflowed = false;
		Network::handleError(16);
	}
	nn::pia::session::Session *pia = nn::pia::session::Session::s_pInstance;
	if (pia == nullptr || pia->stationCount != s_stationCount)                 // +0x48
		return;
	for (SessionEventData &e : s_events) {
		if (!e.pending)
			continue;
		u32 node = convertIdPiaToVitei(e.station);
		int code = 5;
		switch (e.event) {
		case 0:
			code = 1;
			s_nodesChanged = true;
			break;
		case 1:
			code = 2;
			Session::removeLocalNodeId(node, true);
			break;
		case 2:                         // the host changed: the new host's mode script takes over
			code = 3;
			if (Session::isMaster()) {
				AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE);
				int index = mode->findPublic("@updateMaster");
				if (index >= 0) {
					AMXState state;
					mode->freezeState(&state);
					mode->callFunction(index);
					mode->thawState(&state);
				}
			}
			break;
		case 3:
			code = 4;
			break;
		default:
			// "Received unknown session event %#x"
			break;
		}
		// "[Session::SessionEventCB] NetworkNotifyCB[0 - %d](viteiEventCode = %d, viteiNodeID = %x)"
		for (u32 i = 0; i < s_notifyCount; i++)
			s_notify[i](code, node);
		e.pending = false;
	}
}

// 0x0010D52C: a session that is no longer IN_SESSION for the network has failed (16, caller 5). The local
// wireless connection counts the nodes every frame; the Internet one only after a join.
void Session::update()
{
	handleDueEvents();
	if (!s_ready)
		return;
	if (Network::getStatus() != IN_SESSION) {
		setCustomFailure(16, 5);
		amxNetworkError(false);
		Network::performShutdown(true);
	}
	if (!s_nodesChanged) {
		Connection *connection = Network::getActiveConnection();
		if (connection == nullptr || connection->isInternet())                 // vtable +0x40
			return;
	}
	updateNodeCount(getNodeCount(), true);
	s_nodesChanged = false;
}

// ---- the nodes -----------------------------------------------------------------------------------------

// 0x00133350: the node list again from Pia's stations (0xFD: a free slot), without those that left.
static void refreshLocalIndices()
{
	u32 max = Network::getActiveConnection()->maxUnits();                       // vtable +0x44
	for (u32 i = 0; i < max; i++)
		s_nodes[i] = 0;
	s_nodeCount = 0;
	if (nn::pia::transport::StationManager *stations = nn::pia::transport::StationManager::s_pInstance) {
		for (nn::pia::transport::Station *station : stations->stations) {      // +0x38 count, +0x3C array
			if (station->index == 0xFD)                                         // +0x14
				continue;
			u32 node = convertIdPiaToVitei(station->index);
			if (contains(s_removedNodes, max, node))
				continue;
			for (u32 i = 0; i < max; i++) {
				if (s_nodes[i] == 0) {
					s_nodes[i] = node;
					break;
				}
			}
			s_nodeCount++;
		}
	}
	qsort(s_nodes, s_nodeCount, sizeof(u32), compareConnectionIDs);        // 0x0013DFF4, 0x0013F980
	for (u32 i = 0; i < max; i++)
		s_removedNodes[i] = 0;
}

// 0x00123E34: tells the scripts when the count changed (code 0). A session left with no node at all has
// failed (16, caller 5): "[Session::updateNodeCount] NetworkNotifyCB[0 - %d](viteiEventCode = NODE_UPDATE,
// nodeCountNow = %d)".
void Session::updateNodeCount(u32 previous, bool refresh)
{
	if (refresh)
		refreshLocalIndices();
	u32 count = getNodeCount();
	if (count != previous) {
		// (a log of every node: "  %x = %x")
		for (u32 i = 0; i < s_notifyCount; i++)
			s_notify[i](0, count);
	}
	if (count == 0) {
		setCustomFailure(16, 5);
		amxNetworkError(false);
		Network::performShutdown(true);
	}
}

// 0x00123FA4: a node left: out of the list (the ones after it move up), kept in s_removedNodes so that the
// next refresh does not take it back while Pia still lists its station.
void Session::removeLocalNodeId(u32 node, bool refresh)
{
	if (Network::getActiveConnection() == nullptr || !Network::isActive())
		return;
	u32 previous = getNodeCount();
	u32 max = Network::getActiveConnection()->maxUnits();
	bool found = false;
	for (u32 i = 0; i < max; i++) {
		if (found) {
			s_nodes[i - 1] = s_nodes[i];
			s_nodes[i] = 0;
		} else if (s_nodes[i] == node) {
			for (u32 j = 0; j < max; j++) {
				if (s_removedNodes[j] == 0) {
					s_removedNodes[j] = node;
					break;
				}
			}
			s_nodes[i] = 0;
			found = true;
			s_nodeCount--;
		}
	}
	updateNodeCount(previous, refresh);
}

u32 Session::getNodeCount() { return s_ready ? s_nodeCount : 0; }            // 0x0024CC48
u32 Session::getNodeMax() { return 11; }                                    // 0x002EFC14
u32 Session::getNodeIDFromIdx(u32 index) { return s_nodes[index]; }        // 0x002EFDD8

// 0x0024A480: this console's node id, -1 outside a session.
u32 Session::getNodeID()
{
	if (s_ready) {
		nn::pia::session::Session *pia = nn::pia::session::Session::s_pInstance;
		u8 station = pia->localStation;                                        // +0x4E
		if (pia->isValidStation(station))                                      // 0x0023ACA4
			return convertIdPiaToVitei(station);
	}
	return -1;
}

// 0x002EFB10: this console's place in the sorted node list (the same on every console), -1 if none.
u32 Session::getNodeIdx()
{
	u32 node = getNodeID();
	return node == (u32)-1 ? -1 : getNodeIdxFromID(node);
}

// 0x002EFDF0
u32 Session::getNodeIdxFromID(u32 node)
{
	for (u32 i = 0; i < Network::getActiveConnection()->maxUnits(); i++)
		if (s_nodes[i] == node)
			return i;
	return -1;
}

// 0x0024A37C: is this node one of Pia's stations?
bool Session::nodeIsConnected(u32 node)
{
	for (nn::pia::transport::Station *station : nn::pia::transport::StationManager::s_pInstance->stations)
		if (convertIdPiaToVitei(station->index) == node)
			return true;
	return false;
}

u32 Session::convertIdViteiToPia(u32 node) { return node == 0xFFFF ? 0xFF : node - 0xC00001; }  // 0x0024A44C
u32 Session::convertIdPiaToVitei(u32 station) { return station == 0xFF ? 0xFFFF : station + 0xC00001; }  // 0x0024A464

// 0x002F0490: the host: Pia's host station (+0x4D) is ours (+0x4E), a valid index (0..11).
bool Session::isMaster()
{
	nn::pia::session::Session *pia = nn::pia::session::Session::s_pInstance;
	return pia != nullptr && pia->localStation < 12 && pia->localStation == pia->hostStation;
}

u8 Session::getState() { return nn::pia::session::Session::s_pInstance->state; }  // 0x002F0410 (+0x4F)

// 0x002EFC2C: the session's clock (the same on every console), kept when Pia's session is gone.
u64 Session::getSessionTime()
{
	if (nn::pia::session::Session *pia = nn::pia::session::Session::s_pInstance)
		s_sessionTime = pia->sessionTime();                                    // 0x002FD46C
	return s_sessionTime;
}

// ---- small state ---------------------------------------------------------------------------------------

void Session::setReady(bool ready) { s_ready = ready; }                     // 0x0021C344
bool Session::isActive() { return s_ready; }                                // 0x0023ACE8
void Session::setLinkFailure(bool failed) { s_linkFailure = failed; }       // 0x001179DC
bool Session::isLinkFailure() { return s_linkFailure; }                     // 0x0021BD14
int Session::getLastCustomFailure() { return s_customFailure; }             // 0x002EFF40
void Session::setDataRegistered(u32 value) { s_dataRegistered = value; }    // 0x002EFF10
void Session::setSubRegistered(u32 value) { s_subRegistered = value; }      // 0x002EFF00
void Session::setTeamRegistered(u32 value) { s_teamRegistered = value; }    // 0x002EFF20

// 0x0023F28C: "[Session::setCustomFailure] failureCode = %d, caller = %d". The callers: 4
// Network::handleError, 5 the session lost (update, updateNodeCount, abort). Inlined in those.
void Session::setCustomFailure(int code, int caller)
{
	s_customFailure = code;
	s_failureFlag3 = false;
}

// 0x0024A154: up to 10 callbacks (no check).
void Session::registerNotifyCB(SessionNotifyCB callback) { s_notify[s_notifyCount++] = callback; }

// 0x002EFE40: open or close the session to newcomers: the connection's closeParticipation (+0x10) or
// reopenParticipation (+0x14), and Pia's approval callback answers accordingly.
void Session::setParticipation(bool allowed)
{
	sIsParticipationAllowed = allowed;
	if (Connection *connection = Network::getActiveConnection()) {
		if (allowed)
			connection->reopenParticipation();
		else
			connection->closeParticipation();
	}
}

// ---- Pia's session: set up, created, joined, left ------------------------------------------------------

// 0x002EFC5C: Connection::initPIATransport calls it once the transport is up.
bool Session::initPIASession(u32 setting)
{
	if (!nn::pia::session::IsInitialized() && !Network::handleError(nn::pia::session::Initialize()))
		return false;
	if (!Network::handleError(nn::pia::session::BeginSetup()))
		return false;
	nn::pia::session::Session::Setting settings = {setting, 0x100};
	if (!Network::handleError(nn::pia::session::Session::CreateInstance(&settings)))
		return false;
	if (!Network::handleError(nn::pia::session::EndSetup()))
		return false;
	nn::pia::session::Session::s_pInstance->approvalCallback = sessionApprovalCB;   // +0x38
	// "Inet_InitializePiaSession:Pia current memory usage: %d"
	return true;
}

bool Session::finalizePIASession() { nn::pia::session::Finalize(); return true; }  // 0x002EFF30

// 0x002EFF50: before a session is created or joined. Connection::startupSession starts Pia's session
// (signature key, the player's name); then the event callback is set.
bool Session::init()
{
	s_customFailure = 0;
	s_linkFailure = false;
	s_stationCount = 0;
	s_sessionTime = 0;
	memset(s_nodes, 0, sizeof s_nodes);
	memset(s_removedNodes, 0, sizeof s_removedNodes);
	bool ok = Network::getActiveConnection()->startupSession();
	if (!ok) {
		System::enableHomeButton(true);
		System::enableSleep(true);
		return false;
	}
	for (SessionEventData &e : s_events)
		e.pending = false;
	nn::pia::session::Session::s_pInstance->eventCallback = SessionEventCB;      // +0x34
	return true;
}

// 0x002F01DC: this console hosts.
void Session::create()
{
	SyncEvent::reset();
	Network::handleError(nn::pia::session::Session::s_pInstance->CreateSession());
}

// 0x002F0070: joins the session of another console (its station address), waiting with the wait screen.
bool Session::join(const nn::pia::common::StationAddress *host)
{
	SyncEvent::reset();
	nn::pia::common::Time now;
	now.SetNow();
	nn::pia::common::CallContext call;
	nn::pia::session::Session::s_pInstance->JoinSession(host, &call);
	switch (Network::getActiveConnection()->waitCallContext(&call, true, true)) {
	case 1:
		Network::handleError(call.result);
		return false;
	case 2:
		return false;
	default:
		return true;
	}
}

// 0x002F0174: the scripts' netAbort: a failure of the session (16, caller 5) or not, the mode's script is
// told and the session ends.
void Session::abort(bool failure)
{
	if (failure)
		setCustomFailure(16, 5);
	amxNetworkError(false);
	Network::performShutdown(true);
}

// 0x002F0260: leaves the session (unless it already failed: nothing to tell the others). The host leaves
// "with host migration", so that another console takes over the battle. Then Pia's session is cleaned up
// ("[Session::finalize] nn::pia::session::Session::Cleanup, destroy session time:%d [ms]") and the node list
// forgotten. Returns false when leaving could not start.
bool Session::finalize()
{
	bool ok = true;
	nn::pia::session::Session *pia = nn::pia::session::Session::s_pInstance;
	if (pia != nullptr) {
		nn::pia::common::Time start;
		start.SetNow();
		nn::pia::common::CallContext call;
		if (!s_linkFailure && s_customFailure == 0) {
			ok = Network::handleError(isMaster() ? pia->LeaveSessionWithHostMigration(&call)
			                                     : pia->LeaveSession(&call));
			if (Connection *connection = Network::getActiveConnection()) {
				connection->waitCallContext(&call, true, true);
				Network::handleError(call.result);
			}
		}
		pia->Cleanup();
	}
	s_ready = false;
	memset(s_nodes, 0, sizeof s_nodes);
	memset(s_removedNodes, 0, sizeof s_removedNodes);
	for (SessionEventData &e : s_events)
		e.pending = false;
	return ok;
}

// Unused in this build (a log only): "A session function is getting called without a connection. FIXME"
// (0x00355428) sits among session.o's strings, but no code refers to it any more: the developers' FIXME
// outlived the check that printed it.
