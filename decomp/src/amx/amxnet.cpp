// source/amx/amxnet.cpp (amxnet.o): the network natives of the scripts (table natives_Online, registered by
// amx_OnlineInit 0x00171A04), and how the network talks back to the mode script (UID_MODE, 10000).
//
// Reconstructed by hand from decomp/raw/source/amx/amxnet.cpp and the disassembly. Not compilable on its own.
// The network itself is decomp/src/net/. Prototypes for the scripts: decomp/pawn/natives.inc.
// Many natives are 4- or 8-byte thunks placed right before the function they run into (n_netGetStatus
// 0x00242A88 before Network::getStatus 0x00242A8C...); they are listed at the end.

// ---- module state (0x0038DD78..0x0038DD98; 0x003B8B64) -------------------------------------------------
static bool s_masterChanged;            // 0x0038DD78 MASTER_CHANGED received: @updateParticipation next frame
static bool s_wasActive;                // 0x0038DD79 Network::isActive() last frame (guard 0x0038DD7C)
static ScanResult s_scan[4];            // 0x003B8B64 the networks found by netScan (connectionLocal.cpp)

// The names of the Session notify codes, 21 bytes each (0x00352D84), for a log:
// NODE_UPDATE, NODE_JOIN, NODE_QUIT, MASTER_CHANGED, MIGRATION_FAIL, NOTIFICATION_INVALID.

static void callMode(const char *function, int argCount = 0, cell a = 0, cell b = 0)
{
	AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE);
	if (mode == nullptr)
		return;
	int index = mode->findPublic(function);
	if (index < 0)
		return;
	AMXState state;
	mode->freezeState(&state);
	if (argCount == 2) {
		mode->pushArg(b);
		mode->pushArg(a);
	} else if (argCount == 1) {
		mode->pushArg(a);
	}
	mode->callFunction(index);
	mode->thawState(&state);
}

// 0x00107988
void amxOnlineSubsystemInit() { Session::registerNotifyCB(amxOnlineNotifyCB); }

// 0x0011042C (Session notify): what happens in the session goes to the mode script.
// "[amxnet::amxOnlineNotifyCB] notificationID = %d (%s), param = %x"
static void amxOnlineNotifyCB(int code, cell node)
{
	if (AMXLoader::uidToAmx(UID_MODE) == nullptr)
		return;
	switch (code) {
	case NODE_UPDATE:
	case NODE_JOIN:
		callMode("@onlineNotification", 2, code, node);
		break;
	case NODE_QUIT:
		callMode("@processDisconnect", 2, code, node);
		break;
	case MASTER_CHANGED:
		s_masterChanged = true;
		break;
	case MIGRATION_FAIL:                // nobody could take the host's place: the battle is over
		Session::setCustomFailure(16, 0);
		callMode("@networkError", 1, 0);
		AMXLoader::uidToAmx(UID_MODE)->cleanup();
		Network::performShutdown(true);
		break;
	}
}

// 0x002429D8: the network failed. The mode script's @networkError(requiresFinalize) chooses where to go
// (its error message, the next mode), then the mode ends (cleanup: AMXLoader::isFinished becomes true and
// main.cpp starts the next one). "Network error reported to mode" / "Could not report network error to any
// mode!" were its logs.
void amxNetworkError(bool requiresFinalize)
{
	AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE);
	if (mode == nullptr)
		return;
	int index = mode->findPublic("@networkError");
	if (index >= 0) {
		AMXState state;
		mode->freezeState(&state);
		mode->pushArg(requiresFinalize);
		mode->callFunction(index);
		mode->thawState(&state);
	}
	mode->cleanup();                                                 // vtable +0x04
}

// 0x001011E4, every frame (main.cpp, before Network::update): the remote calls run while the session is
// active; when it stops being active, the mode hears of it (amxEventConnectionLost) and the calls waiting
// are dropped. After a new host, the mode script's @updateParticipation.
void amxOnlineUpdate()
{
	static bool initialised = (s_wasActive = Network::isActive(), true);
	if (s_masterChanged) {
		s_masterChanged = false;
		callMode("@updateParticipation");
	}
	if (Network::isActive()) {
		RPC::processQueue();
	} else if (s_wasActive) {
		amxEventConnectionLost();
		RPC::clear();
	}
	s_wasActive = Network::isActive();
}

// ---- connecting ----------------------------------------------------------------------------------------

// 0x00326378: netInit(connection): 0 local wireless, 1 Internet. A connection already there is shut down
// first; the new one is registered and initialised (vtable +0x00).
static cell n_netInit(AMX *, const cell *params)
{
	if (Network::getActiveConnection() != nullptr)
		Network::performShutdown(true);
	Connection *connection = nullptr;
	if (params[1] == 0)
		connection = Connection::local();
	else if (params[1] == 1)
		connection = Connection::inet();
	Network::registerConnection(connection);
	return connection->init();
}

static cell n_netIsInitialized(AMX *, const cell *) { return Network::getActiveConnection() != nullptr; }  // 0x003263E8
static cell n_netLogin(AMX *, const cell *) { return Network::getActiveConnection()->matchmakerLogin(); }  // 0x00326410
static cell n_netFinalize(AMX *, const cell *) { Network::performShutdown(true); return 0; }   // 0x00326180
static cell n_netLeaveSession(AMX *, const cell *) { Network::performShutdown(false); return 1; }  // 0x003263FC
static cell n_netFinalizePIA(AMX *, const cell *) { Connection::finalizePIA(); return 0; }       // 0x00326194

// 0x00326028: netConnect(host). The remote calls and the Miis are reset and listened to, then the connection
// connects: the Internet one searches for a match (host unused); the local one joins the network whose
// address `host` points to: a netGetMasterID() value, a native pointer in a cell (0: the zero address).
static cell n_netConnect(AMX *, const cell *params)
{
	Connection *connection = Network::getActiveConnection();
	const u8 *host = (const u8 *)params[1];
	RPC::clear();
	RPC::registerListeners();
	FaceSystem::registerListeners();
	MacAddress address(host != nullptr ? host : MacAddress::zero);  // (with its text, for a log)
	return connection->connect(address.bytes);                       // vtable +0x20
}

// 0x0032AA70: udsBroadcast(): the same preparation, then the local connection hosts (vtable +0x48).
static cell n_udsBroadcast(AMX *, const cell *)
{
	Connection *connection = Network::getActiveConnection();
	RPC::clear();
	RPC::registerListeners();
	FaceSystem::registerListeners();
	return connection->broadcast();
}

static cell n_udsStopBroadcast(AMX *, const cell *) { return Network::getActiveConnection()->stopBroadcast(); }  // 0x0032AB08

// 0x00326478: netScan(): a scan in the background into s_scan (4 networks at most); the scripts poll
// "local.scanstatus.*". False without a connection.
static cell n_netScan(AMX *, const cell *)
{
	Connection *connection = Network::getActiveConnection();
	if (connection != nullptr)
		connection->scan(s_scan, 4);                                 // vtable +0x1C
	return connection != nullptr;
}

static cell n_netGetMasterID(AMX *, const cell *params) { return (cell)&s_scan[params[1]].host; }  // 0x0032625C

// 0x003261A4: netGetBroadcastData(index, data[]): the application data the host published.
static cell n_netGetBroadcastData(AMX *, const cell *params)
{
	AMXLoader::getCurrentLoader()->setString((const char *)s_scan[params[1]].applicationData, params[2]);
	return 1;
}

// 0x003264CC: netSetBroadcastData(data[]): what this host publishes in its beacon (UdsNode vtable +0x3C).
static cell n_netSetBroadcastData(AMX *, const cell *params)
{
	char data[384];
	AMXLoader::getCurrentLoader()->getString(data, params[1]);
	return nn::pia::local::UdsNode::s_pInstance->SetApplicationData(data, strlen(data)).IsSuccess();
}

// 0x00325C88: inetSetAttribute(index, value): a search criterion (connectionInternet.cpp).
static cell n_inetSetAttribute(AMX *, const cell *params)
{
	ConnectionInternet::setMatchingAttribute(Network::getActiveConnection(), params[1], params[2]);
	return 1;
}

static cell n_netSetParticipation(AMX *, const cell *params) { Session::setParticipation(params[1] != 0); return 1; }  // 0x003265D8
static cell n_netAbort(AMX *, const cell *params) { Session::abort(params[1] != 0); return 0; }  // 0x00325DC0

// ---- errors --------------------------------------------------------------------------------------------

static cell n_netHandleError(AMX *, const cell *params) { Network::handleError(params[1]); return 0; }  // 0x00326364
static cell n_netSetCustomFailure(AMX *, const cell *params) { Session::setCustomFailure(params[1], 2); return 0; }  // 0x00326594
static cell n_netClearCustomFailure(AMX *, const cell *) { Session::setCustomFailure(0, 6); return 0; }  // 0x00326000
static cell n_netSetGenericFailure(AMX *, const cell *) { Session::setCustomFailure(16, 1); return 0; }  // 0x003265C0

// 0x003261E4: the failure to show, read once. The codes of local wireless play from 993000 on (UDS) are
// shown as 16.
static cell n_netGetLastCustomFailure(AMX *, const cell *)
{
	u32 code = Session::getLastCustomFailure();
	Session::setCustomFailure(0, 3);
	return code >= 993000 ? 16 : code;
}

// ---- the session ---------------------------------------------------------------------------------------

// 0x003262A8: netGetSessionTime(time[2]): the session's clock, high word first.
static cell n_netGetSessionTime(AMX *, const cell *params)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	u64 time = Session::getSessionTime();
	cell *out = self->getAddr(params[1], 0);
	out[0] = time >> 32;
	out[1] = (cell)time;
	return 0;
}

// 0x002EFC1C: its low word (Session::getSessionTime inlined).
static cell n_netGetSessionTimeLo(AMX *, const cell *) { return (cell)Session::getSessionTime(); }

// 0x0032627C: the principal id (Internet; the local connection answers 0), -1 without a connection.
static cell n_netGetPID(AMX *, const cell *)
{
	Connection *connection = Network::getActiveConnection();
	return connection != nullptr ? connection->getPID() : -1;           // vtable +0x34
}

// 0x00325DF0: netCallPublic(target, function[], ...): every argument a value ('c'), to every console.
static cell n_netCallPublic(AMX *, const cell *params)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char function[512];
	self->getString(function, params[2]);
	u32 count = params[0] / sizeof(cell) - 2;
	char format[32];
	cell args[26];
	for (u32 i = 0; i < count; i++) {
		args[i] = params[3 + i];
		format[i] = 'c';
	}
	RPC::callPublic(self, self->uid, params[1], function, format, args, count, false, 0xFFFF);
	return 0;
}

// 0x00325ED0: netCallPublicf(target, function[], format[], ...): the format says which arguments are
// strings ('s') or arrays ('a', followed by their length). "Calling function with %d parameters with format
// string "%s" - Length doesn't match." was the log of a format of the wrong length (no longer checked).
static cell n_netCallPublicf(AMX *, const cell *params)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char function[512], format[384];
	self->getString(function, params[2]);
	u32 count = params[0] / sizeof(cell) - 3;
	self->getString(format, params[3]);
	cell args[26];
	for (u32 i = 0; i < count; i++)
		args[i] = params[4 + i];
	RPC::callPublic(self, self->uid, params[1], function, format, args, count, false, 0xFFFF);
	return 0;
}

// ---- the rest: one call each ---------------------------------------------------------------------------

static cell n_netDebug(AMX *, const cell *) { Network::getActiveConnection()->debug(); return 0; }  // 0x00326160
static cell n_netDbgSetVerbose(AMX *, const cell *params) { Connection::dbgSetVerbose(params[1] != 0); return 0; }  // 0x00326144
static cell n_netDbgFlushCache(AMX *, const cell *) { return 0; }             // 0x0032612C
static cell n_netDbgPrintMemory(AMX *, const cell *) { return 0; }            // 0x0032613C
static cell n_netRemoveResult(AMX *, const cell *) { return 0; }              // 0x00326460
static cell n_netAddToBlacklist(AMX *, const cell *params) { ConnectionInternet::addToBlacklist(params[1]); return 0; }  // 0x00325DDC
static cell n_netRemoveFromBlacklist(AMX *, const cell *params) { ConnectionInternet::removeFromBlacklist(params[1]); return 0; }  // 0x0032644C
static cell n_netRemoveFriendsFromBlacklist(AMX *, const cell *) { ConnectionInternet::removeFriendsFromBlacklist(); return 0; }  // 0x0032643C
static cell n_netSendChangesToBlacklist(AMX *, const cell *) { Network::getActiveConnection()->sendChangesToBlacklist(); return 0; }  // 0x003264AC
static cell n_netPauseOutgoing(AMX *, const cell *) { DataRouter::pauseOutgoing(); return 1; }         // 0x0032642C
static cell n_netClearPausedStatus(AMX *, const cell *) { DataRouter::clearPausedStatus(); return 1; } // 0x00326018
static cell n_netSetReadyToUnpause(AMX *, const cell *) { DataRouter::setReadyToUnpause(); return 1; } // 0x003265FC
static cell n_netSyncEventPoint(AMX *, const cell *) { SyncEvent::point(); return 0; }                 // 0x00326644
static cell n_netSyncEventAcknowledgeSync(AMX *, const cell *) { SyncEvent::acknowledgeSync(); return 0; }  // 0x00326634
static cell n_netSetDataRegistered(AMX *, const cell *params) { Session::setDataRegistered(params[1]); return 0; }  // 0x003265AC
static cell n_netSetSubRegistered(AMX *, const cell *params) { Session::setSubRegistered(params[1]); return 0; }    // 0x0032660C
static cell n_netSetTeamRegistered(AMX *, const cell *params) { Session::setTeamRegistered(params[1]); return 0; }  // 0x00326620
static cell n_netResetLengthSentReceived(AMX *, const cell *) { Network::resetLengthSentReceived(); return 0; }    // 0x00326468
static cell n_netGetLengthReceived(AMX *, const cell *) { return Network::isActive() ? Network::getLengthReceived() : 0; }  // 0x00326214
static cell n_netGetLengthSent(AMX *, const cell *params) { return Network::isActive() ? Network::getLengthSent(params[1] != 0) : 0; }  // 0x00326230

// Thunks into the function that follows them (the parameter, when there is one, is params[1]):
//   n_netInitPIA 0x00175E74 Connection::initPIA        n_netGetStatus 0x00242A88 Network::getStatus
//   n_netGetNodeId 0x0024A47C Session::getNodeID       n_netGetNodeCount 0x0024CC44 Session::getNodeCount
//   n_netIsActive 0x00253984 Network::isActive         n_netGetNodeIdx 0x002EFB0C Session::getNodeIdx
//   n_netGetNodeMax 0x002EFC10 Session::getNodeMax     n_netGetNodeIdFromIdx 0x002EFDD0 Session::getNodeIDFromIdx
//   n_netGetNodeIdxFromId 0x002EFDE8 Session::getNodeIdxFromID
//   n_netGetSessionState 0x002F040C Session::getState  n_netIsMaster 0x002F048C Session::isMaster
//   n_netSyncEventCheck 0x002F71AC SyncEvent::check    n_netAllUnitsReadyToUnpause 0x001764AC
//                                                      DataRouter::allUnitsReadyToUnpause
