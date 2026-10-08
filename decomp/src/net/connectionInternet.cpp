// source/net/connectionInternet.cpp (connectionInternet.o): the Internet connection of the online battles:
// the console's network, the login to the game server (NEX), the search for a match ("auto matchmake") and
// the peer-to-peer session that follows (Pia).
//
// Reconstructed by hand from decomp/raw/source/net/connectionInternet.cpp and the disassembly. Not compilable
// on its own. What the server must answer is in docs/online.md; mods/online patches the friends functions
// that gameServerLogin uses, and rewrites MyNotificationEventHandler::ProcessNotificationEvent.
//
// ConnectionInternet is one of the Connection classes (connection.cpp; connectionLocal.cpp is the local
// wireless one): Network::connect() calls init(), then connect() for each search, update() and dispatch()
// every frame, leaveSession() and finalize(). The search runs in the calling thread: each NEX call is started
// with a ProtocolCallContext and waited for by Connection::waitCallContext (1: failed, 2: cancelled).
// Network::status: 0 off, 1 closing, 2 logging in, 3 logged in, 4 searching, 5 leaving, 6 in a session.

// ---- module state (0x0038E660..0x0038E694, .data; 0x0050D000.., .bss; 0x0052E000) -----------------------
static bool socketReady;                        // 0x0038E660 nn::socket initialised (CTRNetInit)
static bool nexGlobals;                         // 0x0038E661 nn::nex::GlobalVariables acquired (init)
static u32 deletedGathering;                    // 0x0038E664 notification 109000: the session was deleted
static u32 gatheringId;                         // 0x0038E668 the session found or created (attemptMatch)
static nn::nex::NgsFacade *ngs;                 // 0x0038E66C the login (matchmakerLogin)
static nn::nex::MatchmakeExtensionClient *matchmaker;  // 0x0038E670 MatchmakeExtension + MatchMaking
static Connection *connection;                  // 0x0038E674 this connection (init), for its wait functions
static u32 ownerPid;                            // 0x0038E678 the session's owner (attemptMatch, notification 4000)
static u32 myPid;                               // 0x0038E67C the console's principal id (gameServerLogin)
static nn::os::Event disconnected;              // 0x0038E680 nn::ac: the access point was lost
static MyNotificationEventHandler notifications;    // 0x0038E684 (vtable 0x003768C0)

// The search attributes (0x0052E000, 6 entries of 12 bytes), set by the scripts' inetSetAttribute(n, value)
// before each search: 0 continent, 1 lobby type, 2 level, 3 version checksum (sysGetVersionChecksum: v0
// 0xB95D7F2B, v5200 868960903); 4 and 5 unused by the game (mods/online reports its anti-cheat in 4).
struct MatchingAttribute {
	u8 kind;                                    // 0 none, 1 this value, 2 a range (never set by the game)
	u32 value, max;
};
static MatchingAttribute attributes[6];

// Players to add to / remove from the server's block list (inetBlockPlayer...), sent by sendChangesToBlacklist.
static nn::nex::qList<u32> blacklistAdd;        // 0x0050D000
static nn::nex::qList<u32> blacklistRemove;     // 0x0050D018

static Pia *pia;                                // 0x003A304C Pia's NexFacade side of the session ("No instance!")

// ---- the console's network: nn::ac (access point) and nn::socket ----------------------------------------

// 0x00183BB8
bool ConnectionInternet::CTRNetInit()
{
	nn::os::Event connected(true);
	if (!Network::handleError(nn::ac::CTR::Initialize()))
		return false;
	nn::ac::CTR::Config config;
	nn::ac::CTR::CreateDefaultConfig(&config);
	if (!Network::handleError(nn::ac::CTR::ConnectAsync(config, &connected)))
		return false;
	waitEvent(&connected, false, true);                    // the system's "connecting" screen
	if (!Network::handleError(nn::ac::CTR::GetConnectResult()))
		return false;
	disconnected.Initialize(true);
	nn::ac::CTR::RegisterDisconnectEvent(&disconnected);
	size_t size = nn::socket::GetRequiredMemorySize(0x10000, 4);
	if (!Network::handleError(nn::socket::Initialize(0x0050E000, size, 0x10000, 4)))
		return false;
	socketReady = true;
	nn::socket::GetPrimaryAddress(...);                    // read for logs that the retail build removed
	nn::socket::GetResolver(...);
	nn::socket::GetDefaultGateway(...);
	return true;
}

// 0x00183DCC
void ConnectionInternet::CTRNetTerm()
{
	if (socketReady) {
		Network::handleError(nn::socket::Finalize());
		socketReady = false;
	}
	disconnected.Finalize();
	nn::os::Event closed(true);
	nn::ac::CTR::CloseAsync(&closed);
	waitEvent(&closed, false, true);
	nn::ac::CTR::Finalize();
}

// 0x00184A74
void ConnectionInternet::init()
{
	nn::nex::ObjectThreadRoot::UseAutoStack(false);
	nn::nex::GlobalVariables::AcquireInstance();
	nexGlobals = true;
	*(int *)0x00399D18 = 2;                                // NEX settings (in its globals)
	*(int *)0x00399DC0 = framesPerSecond() * 5000;         // vtable +0x44
	nn::nex::EventLog::GetInstance()->enabled = true;
	nn::nex::TraceLog::GetInstance()->flags |= 0x747BFF;
	if (Connection::init() && CTRNetInit())
		connection = this;
}

// 0x00184DA0
void ConnectionInternet::finalize()
{
	matchmakerLogout();
	CTRNetTerm();
	nn::pia::inet::NexFacade::DestroyInstance();
	nn::pia::inet::Finalize();
	if (nexGlobals) {
		nn::nex::GlobalVariables::ReleaseInstance();
		nexGlobals = false;
	}
	Connection::finalize();
}

// 0x00184BE4: every frame. A lost access point, or a NEX error, ends the connection with its error code.
u32 ConnectionInternet::update()
{
	u8 status = Network::getStatus();
	if (status != 0) {
		if (disconnected.Wait(0)) {                    // svcWaitSynchronization, timeout 0
			u32 code;
			nn::ac::CTR::GetLastErrorCode(&code);
			if (code != 0)
				return code;
		}
		if (nn::nex::ProductFacade *product = nn::nex::ProductFacade::GetInstance()) {
			qResult result = product->GetLastError();          // vtable +0x14
			if (!result.IsSuccess())
				return Network::getErrorCode(result);
		}
		if (status > 2 && !ngs->IsConnected())             // 0x002F8DC8: both PRUDP connections up
			return Network::getErrorCode(0xD8A14825);
	}
	return Connection::update();
}

// 0x00184D28: NEX's scheduler runs every tenth frame.
bool ConnectionInternet::dispatch()
{
	if (!Connection::dispatch())
		return false;
	if (frame % 10 == 0) {                                 // +0x0C
		nn::nex::Core *core = nn::nex::Core::GetInstance();
		if (core == nullptr || core->scheduler == nullptr)
			return false;
		core->scheduler->Dispatch(0, nullptr);
	}
	return true;
}

bool ConnectionInternet::isInternet() { return true; }  // 0x00183E94
void ConnectionInternet::scan() {}                       // 0x00184BD0 (local wireless only)
u32 ConnectionInternet::getPID() { return myPid; }       // 0x00184BD4
int ConnectionInternet::maxUnits() { return 8; }         // 0x00184DE8

// ---- login: the friends module, then the game server --------------------------------------------------

// 0x00171D00: the friends module logs in to Nintendo's servers, then NgsFacade::Login asks it for the
// game server's address and a token (JobCTRLogin: GetMyPrincipalId, GetMyPassword, then
// RequestGameAuthentication / GetGameAuthenticationData: what mods/online answers itself).
static bool gameServerLogin(nn::nex::NgsFacade *ngs, u32 gameServerId, const wchar_t *accessKey, u32 timeout)
{
	nn::os::Event loggedIn(true);
	if (!Network::handleError(nn::friends::CTR::detail::Login(&loggedIn)))
		return false;
	if (connection->waitEvent(&loggedIn, true, true) == 2)
		return false;
	if (!Network::handleError(nn::friends::CTR::detail::GetLastResponseResult()))
		return false;
	myPid = nn::friends::CTR::detail::GetMyPrincipalId();
	nn::friends::CTR::detail::HasLoggedIn();
	nn::nex::ProtocolCallContext call;
	nn::nex::BackEndServices::RegisterNotificationEventHandler(ngs, &notifications);
	qResult started = ngs->Login(&call, gameServerId, accessKey, timeout, false);
	if (!started.IsSuccess())
		return Network::handleError(call.outcome);
	switch (connection->waitCallContext(&call, true, true, true)) {
	case 1:
		Network::handleError(ngs->GetLastLoginError(), 0x1E8, 0, "NgsFacade::Login() failed. Error code : %d\n");
		return false;
	case 2:
		return false;
	}
	if (!ngs->IsConnected()) {
		Network::handleError(0x8213);
		return false;
	}
	return true;
}

// 0x00184248: Network::login(), from the scripts' netLogin (mode_internet_menu).
bool ConnectionInternet::matchmakerLogin()
{
	Network::setStatus(2);
	*(u8 *)0x00396716 = 0;
	{
		ScopedHeap heap(System::getNetHeap());
		ngs = new nn::nex::NgsFacade();                    // 0x148 bytes
		matchmaker = new nn::nex::MatchmakeExtensionClient();  // 0xE8 bytes
	}
	if (nn::nex::Core *core = nn::nex::Core::GetInstance())
		core->SetTerminateImmediately(false);
	// The current context's PRUDP settings: +0x108 = 1 (the same block is read twice, "source/net/
	// connectionInternet.cpp" line 0x3C5 when there is no context)
	currentContext()->transportSettings->flag108 = true;
	if (!gameServerLogin(ngs, 0xD7C00, L"fb9537fe", 60000))
		return false;
	if (!matchmaker->Bind(ngs->credentials)) {             // vtable +0x0C, NgsFacade +0x78
		Network::handleError(0x8213);
		return false;
	}
	if (!Inet_InitializePiaInet())
		return false;
	if (!startPia(&piaSettings))                           // vtable +0x50, settings 0x0037A3BC
		return false;
	Network::setStatus(3);
	return true;
}

// 0x00174780
static bool Inet_InitializePiaInet()
{
	u32 memory = 0x554;
	return Network::handleError(nn::pia::inet::Initialize(&memory))
	    && Network::handleError(nn::pia::inet::BeginSetup())
	    && Network::handleError(nn::pia::inet::NexFacade::CreateInstance())
	    && Network::handleError(nn::pia::inet::EndSetup());
}

// 0x001727D4: Network::logout().
static void matchmakerLogout()
{
	if (Network::getStatus() == 0)
		return;
	Network::setStatus(1);
	if (nn::nex::Core *core = nn::nex::Core::GetInstance())
		core->SetTerminateImmediately(true);
	if (connection != nullptr)
		connection->stopPia();                             // vtable +0x54
	nn::pia::session::Session::DestroyInstance();
	ScopedHeap heap(System::getNetHeap());
	if (ngs != nullptr)
		nn::nex::BackEndServices::UnregisterNotificationEventHandler(ngs, &notifications);
	if (matchmaker != nullptr) {
		matchmaker->Unbind();                              // vtable +0x10
		delete matchmaker;
		matchmaker = nullptr;
	}
	if (ngs != nullptr) {
		if (!Session::isLinkFailure()) {
			nn::nex::ProtocolCallContext call;
			ngs->Logout(&call);
			int waited = connection->waitCallContext(&call, true, true, true);
			if (waited != 1 && waited != 2)
				nn::friends::CTR::detail::Logout();
		}
		delete ngs;
		ngs = nullptr;
	}
	Network::setStatus(0);
}

// ---- the search for a match -----------------------------------------------------------------------------

// 0x0018469C: inetSetAttribute(n, value).
void ConnectionInternet::setMatchingAttribute(int n, u32 value)
{
	attributes[n].kind = 1;
	attributes[n].value = value;
}

// 0x00172D50: one criteria set, appended to the list: 1 to 8 participants, game mode 1000, the attributes
// set by the scripts (exact values; a range when kind is 2), matchmake system type 1 (anybody).
static void setupCriteriaList(nn::nex::qList<nn::nex::MatchmakeSessionSearchCriteria> &list)
{
	nn::nex::MatchmakeSessionSearchCriteria criteria;
	criteria.SetMinParticipants(1);
	criteria.SetMaxParticipants(8);
	criteria.SetGameMode(1000);
	for (u32 n = 0; n < 6; n++) {
		if (attributes[n].kind == 1)
			criteria.SetAttribute(n, attributes[n].value);
		else if (attributes[n].kind == 2)
			criteria.SetAttributeWithRange(n, attributes[n].value, attributes[n].max);
	}
	criteria.SetMatchmakeSystemType(1);
	list.push_back(criteria);
}

// 0x001742E0: the session the console offers to create when nothing matches ("Steel Matcher").
static void initMatchmakeSession(nn::nex::MatchmakeSession *session)
{
	session->openParticipation = false;                    // +0x44: opened by openMatchmakingSession
	session->SetDescription(L"Steel Matcher");
	session->minParticipants = 1;                          // +0x14
	session->maxParticipants = 8;                          // +0x16
	session->gameMode = 1000;                              // +0x34
	for (u32 n = 0; n < 6; n++) {
		if (attributes[n].kind == 1 || attributes[n].kind == 2)
			session->SetAttribute(n, attributes[n].value);
	}
	session->SetMatchmakeSystemType(1);
	nn::nex::qVector<u8> buffer = {1, 2, 3};
	session->SetApplicationBuffer(buffer);
	session->flags |= 0x10;                                // +0x20
}

// 0x001712F0: MatchmakeExtension::AutoMatchmakeWithSearchCriteria_Postpone (method 15): the server joins
// the console to a session that matches the criteria, or creates the one offered. *owner: its owner.
static bool attemptMatch(nn::nex::MatchmakeExtensionClient *client, u32 *owner)
{
	*owner = 0;
	nn::nex::qList<nn::nex::MatchmakeSessionSearchCriteria> criteria;
	setupCriteriaList(criteria);
	nn::nex::MatchmakeSession *offered;
	{
		ScopedHeap heap(System::getNetHeap());
		offered = new nn::nex::MatchmakeSession();         // 0x70 bytes
	}
	initMatchmakeSession(offered);
	nn::nex::Gathering *found = nullptr;
	nn::nex::ProtocolCallContext call;
	if (!client->AutoMatchmake(&call, criteria, offered, &found, L"Steel Diver 2 Auto matchmake"))
		return Network::handleError(call.outcome);
	switch (connection->waitCallContext(&call, true, true, true)) {
	case 1:
		Network::handleError(call.outcome);
		return false;
	case 2:
		return false;
	}
	gatheringId = found->id;                               // +0x08
	*owner = found->ownerPid;                              // +0x0C (+0x10: the host, unused)
	return true;
}

// 0x001749E4: the console owns the session: it hosts the Pia session, then lets others in.
static bool openMatchmakingSession(nn::nex::MatchmakeExtensionClient *client, u32 gathering)
{
	if (!Session::create(client, gathering))
		return false;
	nn::nex::ProtocolCallContext call;
	if (!client->OpenParticipation(&call, gathering))
		return false;
	switch (connection->waitCallContext(&call, true, true, true)) {
	case 1:
		Network::handleError(call.outcome);
		return false;
	case 2:
		return false;
	}
	return true;
}

// 0x00174808: another console owns it: MatchMaking::GetSessionURLs gives the station URLs of its host.
static bool joinMatchmakingSession(nn::nex::MatchmakeExtensionClient *client)
{
	nn::nex::qList<nn::nex::StationURL> urls;
	nn::nex::ProtocolCallContext call;
	if (!client->GetSessionURLs(&call, gatheringId, &urls))
		return Network::handleError(call.outcome);
	switch (connection->waitCallContext(&call, true, true, true)) {
	case 1:
		Network::handleError(call.outcome);
		return false;
	case 2:
		return false;
	}
	for (nn::nex::StationURL &url : urls)
		url.GetURL();                                      // "URL = %ls\n", a log the retail build removed
	return joinNexGame(urls);
}

// 0x001711D0: Pia joins the host from its URLs (pia::inet::NexConnectStationJob picks the private or the
// public address: docs/online.md §7).
static bool joinNexGame(nn::nex::qList<nn::nex::StationURL> &urls)
{
	nn::pia::transport::StationConnectionInfo station;
	if (pia == nullptr)
		Network::handleError(2, "No instance! %s: %d\n");
	if (!Network::handleError(nn::pia::inet::NexFacade::ConvertNexStationURLToStationConnectionInfo(urls, &station)))
		return false;
	if (!Session::join(&station))
		return false;
	Session::setReady(true);
	return true;
}

// 0x00183ED4: one search. Pia's NAT check and session startup first, then the match, then the session:
// created (we own it) or joined.
bool ConnectionInternet::automatchOpen()
{
	ownerPid = 0;
	if (!Network::handleError(pia->setup(ngs)))            // vtable +0x00, with the game server id 0xD7C00
		return false;
	nn::pia::common::CallContext started;
	if (!Network::handleError(pia->startup(&started)))     // vtable +0x08
		return false;
	switch (connection->waitCallContext(&started, true, true)) {
	case 1:
		Network::handleError(started.result);
		return false;
	case 2:
		return false;
	}
	u32 owner = 0;
	if (!attemptMatch(matchmaker, &owner))
		return false;
	pia->gathering = gatheringId;                          // +0x10
	if (!Session::init())
		return false;
	bool ok = owner == matchmaker->credentials->pid        // +0x08 -> +0x0C: our own principal id
	        ? openMatchmakingSession(matchmaker, gatheringId)
	        : joinMatchmakingSession(matchmaker);
	if (!ok)
		return false;
	Session::setReady(true);
	ownerPid = owner;
	connection->onConnected();                             // vtable +0x28
	return true;
}

// 0x00184CE8: Network::connect(), from the scripts' netConnect (joinSession).
bool ConnectionInternet::connect()
{
	Network::setStatus(4);
	if (!automatchOpen()) {
		disconnect();                                      // vtable +0x30
		return false;
	}
	Network::setStatus(6);
	return true;
}

// 0x001844D4: inetCloseParticipation, five seconds before the battle (lobby.inc): nobody else may join.
bool ConnectionInternet::closeParticipation()
{
	if (matchmaker == nullptr)
		return true;
	nn::nex::ProtocolCallContext call;
	if (!matchmaker->CloseParticipation(&call, gatheringId))
		return false;
	switch (connection->waitCallContext(&call, true, true, false)) {
	case 1:
		Network::handleError(call.outcome);
		return false;
	case 2:
		return false;
	}
	return true;
}

// 0x00183E9C: Network::leave().
bool ConnectionInternet::leaveSession()
{
	u8 status = Network::getStatus();
	if (status != 6 && status != 4)
		return true;
	Network::setStatus(5);
	bool ok = automatchCleanup();
	Network::setStatus(3);
	return ok;
}

// 0x0017263C: the Pia session ends; the console tells the server it left, unless the link failed, or it was
// the host and Pia ended without a failure of its own (the server then deletes the session).
static bool automatchCleanup()
{
	bool ok = true;
	bool master = Session::isMaster();
	Session::finalize();
	if (pia != nullptr && pia->started)                    // +0x39
		pia->cleanup();                                    // vtable +0x0C
	if (!Session::isLinkFailure() && matchmaker != nullptr && (!master || Session::getLastCustomFailure()))
		ok = endParticipation(matchmaker, gatheringId);
	pia->destroy();                                        // vtable +0x04
	return ok;
}

// 0x00172718: MatchMaking::EndParticipation, unless the server already deleted the session (notification
// 109000).
static bool endParticipation(nn::nex::MatchmakeExtensionClient *client, u32 gathering)
{
	if (deletedGathering != 0)
		return true;
	nn::nex::ProtocolCallContext call;
	if (!client->EndParticipation(&call, gathering, L""))
		return false;
	int waited = connection->waitCallContext(&call, true, true, true);
	return waited != 1 && waited != 2;
}

// ---- the block list (players the console does not want to meet again) -----------------------------------

// 0x001840E0: inetBlockPlayer. The pid goes into the list to add (no duplicate), out of the list to remove.
void ConnectionInternet::addToBlacklist(u32 pid)
{
	blacklistAdd.push_back(pid);
	blacklistAdd.sort();                                   // 0x0021356C
	blacklistAdd.unique();                                 // 0x002134F8
	blacklistRemove.remove(pid);
}

// 0x00184584: the other way round.
void ConnectionInternet::removeFromBlacklist(u32 pid)
{
	blacklistRemove.push_back(pid);
	blacklistRemove.sort();
	blacklistRemove.unique();
	blacklistAdd.remove(pid);
}

// 0x00184914: netRemoveFriendsFromBlacklist (title screen): the console's friends (100 at most) are never
// blocked.
void ConnectionInternet::removeFriendsFromBlacklist()
{
	nn::friends::FriendKey friends[100];
	size_t count = 0;
	nn::friends::CTR::detail::GetFriendKeyList(friends, &count, 0, 100);
	for (size_t i = 0; i < count; i++)
		removeFromBlacklist(friends[i].principalId);
}

// 0x001846BC: MatchmakeExtension::AddToBlackList / RemoveFromBlackList; a list is emptied once the server
// has it.
void ConnectionInternet::sendChangesToBlacklist()
{
	if (matchmaker == nullptr)
		return;
	nn::nex::ProtocolCallContext call;
	if (!blacklistAdd.empty()) {
		matchmaker->AddToBlackList(&call, blacklistAdd);
		int waited = connection->waitCallContext(&call, true, true, true);
		if (waited == 1 || waited == 2)
			return;
		blacklistAdd.clear();
	}
	if (!blacklistRemove.empty()) {
		matchmaker->RemoveFromBlackList(&call, blacklistRemove);
		int waited = connection->waitCallContext(&call, true, true, true);
		if (waited != 1 && waited != 2)
			blacklistRemove.clear();
	}
}

// ---- notifications of the server (NotificationEvent: +0x0C type, +0x10 param1, +0x14 param2) -------------

// 0x00185264: the retail build only keeps three; the rest of the function wrote logs that were removed.
void MyNotificationEventHandler::ProcessNotificationEvent(const nn::nex::NotificationEvent &event)
{
	nn::nex::StringStream log;
	log << event;                                          // for a log the retail build removed
	switch (event.type / 1000) {
	case 3:                                                // 3001: a player joined
		if (event.type == 3001)
			deletedGathering = 0;
		break;
	case 4:                                                // 4000: the owner changed (param2: the new owner)
		ownerPid = event.param2;
		break;
	case 109:                                              // 109000: the session was deleted (param1: its id)
		deletedGathering = event.param1;
		break;
	}
}

// 0x0031527C: static initialisation: the two block lists (empty), the disconnection event, the handler.
