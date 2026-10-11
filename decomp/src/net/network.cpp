// source/net/network.cpp (network.o): the game's network front, above the two connections (Internet:
// connectionInternet.cpp, local wireless: connectionLocal.cpp). It keeps the network status, routes the
// data to and from the connection, and turns every error of the SDK, NEX and Pia into one of Nintendo's
// network error codes (shown as XXX-YYYY: code / 10000, code % 10000), then decides what the game does
// with it.
//
// Reconstructed by hand from decomp/raw/source/net/network.cpp and the disassembly. Not compilable on its
// own. The developers' NN_LOG calls are compiled out of the retail build (each left a "mov r0, r0" where the
// call was); their format strings remain and are quoted where they help.
// Network::handleError(int)'s table was taken by running the function itself over every code from 0 to
// 2^20 (an ARM emulator, the game's own code): the result below is exact for that range.

// Network::status (the names come from the game's own table at 0x00354FC4, read by setStatus's log).
enum NetStatus : u8 {
	DISCONNECTED = 0,
	LOGGING_OUT = 1,
	LOGGING_IN = 2,
	LOGGED_IN = 3,
	JOINING_SESSION = 4,
	LEAVING_SESSION = 5,
	IN_SESSION = 6,                     // the scripts' NET_IN_SESSION
};

// ---- module state (0x0038E760..0x0038E7A0, .data; 0x0052E5EC.., .bss) ----------------------------------
static NetStatus s_status;              // 0x0038E760
static bool s_shuttingDown;             // 0x0038E761 performShutdown is running (not reentrant)
static bool s_finalizeRequested;        // 0x0038E762 performShutdown(true) was asked: the connection goes too
static DataFount s_dataFount;           // 0x0038E764 DataRouter::dataFountRoute: what to send this frame
static DataListener s_dataListener;     // 0x0038E768 DataRouter::dataListenerRoute: what was received
static u32 s_lengthSent[2];             // 0x0038E76C/70 getLengthSent(reliable): only reset, never counted
static u32 s_lengthReceived;            // 0x0038E774 bytes received since resetLengthSentReceived
static u32 s_largestPacket;             // 0x0038E778 largest packet received
static u32 s_frame;                     // 0x0038E77C 0..4: slot of s_receivedPerFrame for this frame
static Connection *s_connection;        // 0x0038E780 the active connection (registerConnection)
static u32 s_received[5];               // 0x0052EB4C bytes received in each of the last 5 frames
// A static object built by __sti___11_network_cpp (0x0030E738: -1, -1, 0, 0 at 0x0038E790) and read by
// nothing: the same pattern follows every net/ file (connection.cpp, session.cpp); a debug or profiling
// object whose uses were compiled out.

// The packet being sent (0x0052E5EC, built on first use: __cxa_guard at 0x0038E784).
static u8 s_packet[0x52E];              // filled by the data fount
static u32 s_packetLength;              // 0x0052EB1C 0: nothing waiting
static bool s_packetReliable;           // 0x0052EB20
static u32 s_packetDestination;         // 0x0038E788 node id, 0xFFFF: every node

// ---- the active connection ----------------------------------------------------------------------------

// 0x002EFA68: "[Network::registerConnection] Connection = %x".
void Network::registerConnection(Connection *connection)
{
	s_connection = connection;
	Connection::registerReceiver(connection, NetReceiveCB);
}

Connection *Network::getActiveConnection() { return s_connection; }  // 0x00242900
NetStatus Network::getStatus() { return s_status; }                   // 0x00242A8C

// 0x0021BC7C: "[Network::setStatus] %s -> %s". Leaving a session forgets the Miis received from the others.
void Network::setStatus(NetStatus status)
{
	if (s_status == IN_SESSION && status != IN_SESSION)
		FaceSystem::reset();
	s_status = status;
}

// 0x00253988
bool Network::isActive()
{
	return s_connection != nullptr && s_status == IN_SESSION && Session::isActive();
}

// 0x00242910: ends the session (when there is one: the connection's leaveSession), then, if finalize was
// asked by this call or an earlier one, the connection itself. Called by handleError for any error that
// requires a shutdown, and by the session when it is lost.
void Network::performShutdown(bool finalize)
{
	s_finalizeRequested |= finalize;
	if (s_shuttingDown)
		return;
	s_shuttingDown = true;
	switch (s_status) {
	case JOINING_SESSION:
	case IN_SESSION:
		if (s_connection == nullptr)
			break;
		s_connection->leaveSession();                                      // vtable +0x30
		// fall through
	case DISCONNECTED:
	case LOGGING_OUT:
	case LOGGING_IN:
	case LOGGED_IN:
	case LEAVING_SESSION:
		if (s_connection != nullptr && s_finalizeRequested) {
			s_connection->finalize();                                      // vtable +0x04
			s_connection = nullptr;
		}
		break;
	default:
		// "[Network::handleError] Unhandled case for status = %d!" (sic: the log names handleError)
		break;
	}
	s_shuttingDown = false;
	s_finalizeRequested = false;
}

// ---- every frame (main loop) ---------------------------------------------------------------------------

// 0x00104854: the connection's own checks (lost access point, NEX or Pia error), then the session's.
void Network::update()
{
	if (s_connection == nullptr)
		return;
	if (int error = s_connection->update(true))                          // vtable +0x0C
		handleError(error);
	Session::update();
	s_frame = (s_frame + 1) % 5;
}

// 0x001048B4: lets Pia (and NEX for the Internet) run.
void Network::dispatch()
{
	if (s_connection != nullptr)
		s_connection->dispatch();                                          // vtable +0x28
}

// 0x001046F4: reads everything received; true when the connection stopped on Pia's "no more data"
// (0xD1614828), false on any other result.
bool Network::recv()
{
	if (s_connection == nullptr)
		return false;
	int code = s_connection->recv();                                      // vtable +0x2C
	return code == nn::pia::util::NetworkErrorCodeConverter::Convert(0xD1614828);
}

// 0x00104740: sends the packets of this frame, once there is someone to send them to. The data fount
// (DataRouter) fills a packet; one the connection could not take (a reliable send whose buffer is full)
// stays for the next frame. Returns false only then.
bool Network::send()
{
	if (s_dataFount == nullptr || Session::getNodeCount() < 2)
		return true;
	if (s_packetLength == 0) {
		s_packetDestination = 0xFFFF;
		s_packetLength = s_dataFount(s_packet, 0, &s_packetDestination, sizeof s_packet, &s_packetReliable);
		if (s_packetLength == 0)
			return true;
	}
	if (!s_connection->send(s_packet, s_packetLength, s_packetDestination, s_packetReliable)  // vtable +0x24
	    && s_packetReliable)
		return false;
	s_packetLength = 0;
	return true;
}

void Network::registerDataFount(DataFount fount) { s_dataFount = fount; }            // 0x0010D50C
void Network::registerDataListener(DataListener listener) { s_dataListener = listener; }  // 0x0010D51C

// 0x00171288: the connection's receiver (Connection::recv calls it for each packet).
static void NetReceiveCB(u32 sourceNode, const u8 *data, u32 length)
{
	if (length == 0 || s_dataListener == nullptr)
		return;
	s_dataListener(data, length, 0, sourceNode);
	s_lengthReceived += length;
	s_received[s_frame] = length;
	if (length > s_largestPacket)
		s_largestPacket = length;
}

// 0x002EF150 / 0x002EFA58 / 0x002EFAF0: the scripts' netGetLengthSent / netGetLengthReceived (amxnet.cpp).
u32 Network::getLengthSent(bool reliable) { return reliable ? s_lengthSent[0] : s_lengthSent[1]; }
u32 Network::getLengthReceived() { return s_lengthReceived; }
void Network::resetLengthSentReceived() { s_lengthSent[0] = s_lengthSent[1] = s_lengthReceived = 0; }

// ---- error codes ---------------------------------------------------------------------------------------

// 0x0021A830: the network error code of an SDK result, by the module that returned it (bits 10..17).
int Network::getErrorCode(nn::Result result)
{
	switch (result.module()) {
	case 39: {                                            // nn::ac (the access point)
		int code = 0;
		nn::ac::CTR::GetLastErrorCode(&code);
		return code;
	}
	case 49:                                              // nn::friends
		return nn::friends::CTR::detail::ResultToErrorCode(result);
	case 68:                                              // nn::uds (local wireless)
		return getErrorCodeUDS(result);
	case 82:                                              // Pia
		return nn::pia::util::NetworkErrorCodeConverter::Convert(result);
	default:
		return 0;
	}
}

// 0x00172014: the codes 099-xxxx of local wireless play (the UDS results Pia does not convert).
static int getErrorCodeUDS(nn::Result result)
{
	switch (result.raw) {
	case 0xC88113FA: return 993001;
	case 0xC8611001: return 990001;
	case 0xC92113FB: return 991019;
	case 0xC92113FE: return 991022;
	case 0xC8A113EA: return 991002;
	case 0xC90113FA: return 993002;
	case 0xC86113F3: return 993003;
	case 0xC86113F0: return 993004;
	case 0xC9411002: return 8;
	case 0xE0A113F8: return 991016;
	case 0xE06113F9: return 993005;
	case 0xE10113FD: return 991021;
	case 0xE10113F1: return 991009;
	case 0xE10113F2: return 991010;
	case 0xE10113E9: return 993006;
	case 0xE10113EA: return 993007;
	case 0xD1611004: return 993008;
	case 0xC8C113F4: return 993009;
	case 0xE1211005: return 993010;
	case 0xE0E113F6: return 993011;
	case 0xC8A113FB: return 993012;
	case 0xE1211008: return 993013;
	case 0xF8C11006: return 993014;
	case 0xF9611007: return 993015;
	default:         return 16;
	}
}

// 0x0021C354: an SDK result. Success: true. A failure becomes its error code and goes to handleError(int).
bool Network::handleError(nn::Result result)
{
	if (result.IsSuccess())
		return true;
	int code = getErrorCode(result);
	printResultError(result);                              // 0x002EF628: comparisons for a log that is gone
	return handleError(code);
}

// 0x0021BEF8: a NEX result (qResult: its value, then where it was set).
bool Network::handleError(const nn::nex::qResult &result)
{
	if (result.IsSuccess())                                // 0x0021BD24: bit 31 clear
		return true;
	int code = nn::nex::ErrorCodeConverter::ConvertToNetworkErrorCode(result);
	printResultError(result);
	return handleError(code);
}

// 0x002EF168: "[Network::printResultError] return code = %d, error name = %S". Compares the result with
// NEX's known ones (0x80030001.. 0x80030076, 0x800300C8..0x800300CE: the RendezVous errors) to name it in
// the log; the log is gone, the comparisons remain and do nothing.
void Network::printResultError(const nn::nex::qResult &result) {}

// 0x0024C390: what an error code does. Returns true when the code is not an error (0 and a few others),
// false otherwise. The developers named the outcomes in their log (format string at 0x00355114):
//
//   "[Network::handleError] errorCode = %d, doShowErrorCode = %d, doAppSideHandling = %d,
//    doProductionError = %d, requiresShutdown = %d, requiresFinalize = %d"
//
//   doShowErrorCode     the system's error viewer shows the code (System::showErrEULA)
//   doAppSideHandling   the game handles it itself: Session::setCustomFailure(customCode, caller 4); the
//                       scripts read it back with netGetLastCustomFailure and show their own message
//   doProductionError   the developers' own reminder, logged with "Received error code %d! This should
//                       be resolved during production." (0x003551B0): codes they expected never to see
//                       in the released game (NEX's own internal errors)
//   requiresShutdown    performShutdown(requiresFinalize): leave the session
//   requiresFinalize    ... and close the connection (the player goes back to the menus)
//   linkFailure         Session::setLinkFailure(true) (no name in the log)
//
// Then, for any error, the mode's script is told (amxNetworkError(requiresFinalize)), except for 018-0301
// (180301: the session's owner closed it; the game expects it).
//
// The table, codes not listed: doShowErrorCode, requiresShutdown (an unknown error is shown and ends the
// session, the connection stays):
//
//   code(s)                       show app  prod  shutdown finalize link custom
//   0, 60514-60518, 60931,        -    -    -     -        -        -    -      (not an error)
//   60936, 60978, 61027
//   8                             -    x    -     x        x        -    8
//   16                            -    x    -     x        -        -    16
//   10000-19999                   x    -    -     x        x        -    -
//   30000-33298, 33300-34199      x    -    -     x        x        x    -
//   33299 (003-3299)              -    x    -     x        -        -    16
//   60000                         -    x    -     x        -        -    16
//   60100-60104, 60106-60117,     x    -    -     x        x        -    -
//   60502, 60800-60813
//   60105                         x    -    -     x        x        x    -
//   60322-60328, 60602-60611,     -    x    -     x        -        -    16
//   60613-60616, 60914, 61007,
//   61105-61106, 61203-61204,
//   61206-61208
//   60902, 60916-60917, 60919-60920, 60923-60930, 60932, 60951-60969, 60972-60976, 61009-61010,
//   61012-61013, 61015-61017, 61020, 61024, 61026, 61101-61102, 61104, 61107-61109, 61201-61202,
//   61210-61211                   -    -    x     x        -        -    -
//   98111                         -    -    -     x        x        x    -
//   180001-180003, 180007-180008, 180011-180012, 180101, 180202, 180401-180402,
//   180504-180505                 -    -    x     x        -        -    -
//   180004-180005, 180009-180010, -    x    -     -        -        -    16     (the session goes on)
//   180302-180304, 180404, 180602
//   180301                        -    x    -     -        -        -    16     (scripts not told)
//   180006                        -    x    -     x        x        x    16
//   180013, 180305-180306,        -    x    -     x        -        -    16
//   180403, 180601, 180603-180605
//   180014                        -    x    -     x        x        -    16
//   180201, 180203                x    -    -     x        x        -    -
//   180501-180503, 180506-180507, -    x    -     x        -        -    the code itself
//   180510-180512, 990001,
//   991002, 991009-991010,
//   991016, 991021-991022,
//   993001-993015
//   991019                        -    x    -     x        x        -    the code itself
bool Network::handleError(int code)
{
	ErrorHandling h = classify(code);                      // the table above (a switch of 2,228 bytes)
	bool handled = !(h.showErrorCode || h.appSideHandling || h.productionError || h.requiresShutdown
	                 || h.requiresFinalize || h.linkFailure);
	if (h.linkFailure)
		Session::setLinkFailure(true);
	if (h.appSideHandling)
		Session::setCustomFailure(h.customCode, 4);
	if (h.requiresShutdown)
		performShutdown(h.requiresFinalize);
	if (h.showErrorCode)
		System::showErrEULA(code);
	if (code != 180301 && !handled)
		amxNetworkError(h.requiresFinalize);
	return handled;
}
