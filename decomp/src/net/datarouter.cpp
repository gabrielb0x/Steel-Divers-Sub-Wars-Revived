// source/net/datarouter.cpp (datarouter.o): puts several streams of data into the one packet that Network
// sends each frame, and hands what is received to the stream it belongs to. It also carries the network
// pause (a battle paused for everybody) and its end.
//
// Reconstructed by hand from decomp/raw/source/net/datarouter.cpp and the disassembly. Not compilable on its
// own.
//
// A packet is a run of chunks, each with a 9-byte header:
//   u8  channel     the listener it goes to (0..5)
//   u32 node        its addressee: a node id (session.cpp), 0xFFFF for every console
//   u32 length      of the data that follows
// The channels: 0 the pause (below), 1, 2 and 5 DataStreamer (datastreamer.cpp: actors, RPC, files), 4
// SyncEvent (syncevent.cpp). Two sources ("founts") fill the packets: DataStreamer and SyncEvent; there is
// room for three.

// ---- module state (0x0038E6E8..0x0038E708, .data; 0x0052E048..0x0052E084, .bss) ------------------------
static bool s_sendUnpause;              // 0x0038E6E8 everybody is ready: tell it at once
static u8 s_chunkChannel;               // 0x0038E6E9 the chunk waiting in s_chunk (did not fit)
static u32 s_fountIndex;                // 0x0038E6F0 the fount whose turn it is (0..2)
static u32 s_pausedStations;            // 0x0038E6F4 bit per Pia station still paused (not ready)
static u32 s_chunkNode;                 // 0x0038E6F8
static u32 s_chunkLength;               // 0x0038E6FC
static int s_pauseResend;               // 0x0038E700 frames before the pause notification is sent again
static u32 s_fountCount;                // 0x0038E6EC
static DataListener s_listeners[6];     // 0x0052E048
static DataFount s_founts[3];           // 0x0052E060
static u32 s_chunksSent[3];             // 0x0052E06C debug totals, per fount (dbgTotalsClear, read by
static u32 s_bytesSent[3];              // 0x0052E078 nothing; bytes adds the packet's running total)
static u8 s_chunk[0x52E];               // 0x0052E084

// The pause notification (channel 0, reliable, to everybody): "PAUS" and the sender's paused stations.
static const u32 PAUSE_NOTIFICATION_HDR = 0x50415553;    // 'P' 'A' 'U' 'S' read as a little-endian u32
struct PauseNotification {
	u32 header;
	u32 pausedStations;
};

// 0x00101400
void DataRouter::init()
{
	Network::registerDataFount(dataFountRoute);
	Network::registerDataListener(dataListenerRoute);
	s_listeners[0] = pausedDataListener;
}

void DataRouter::registerDataFount(DataFount fount) { s_founts[s_fountCount++] = fount; }   // 0x0024A2D8
void DataRouter::registerDataListener(DataListener listener, int channel) { s_listeners[channel] = listener; }  // 0x0024A2FC

// 0x001013D4: from main.cpp's debug menu.
void DataRouter::dbgTotalsClear()
{
	for (int i = 0; i < 3; i++)
		s_chunksSent[i] = s_bytesSent[i] = 0;
}

// 0x001070B8 (Network's data fount): fills the packet of this frame. Normally the founts take turns, each
// adding chunks until it has nothing more or the packet is full (a chunk that does not fit waits for the next
// frame, first in it). The packet goes to the node of its chunks, or to everybody when they differ; it is
// reliable as soon as one chunk asks for it.
// While a network pause runs, nothing else is sent: a console ready to go on (its own station's bit clear)
// sends its view of who is still paused every 30 frames, and at once when it saw everybody ready.
static u32 dataFountRoute(u8 *packet, u32, u32 *node, u32 size, bool *reliable)
{
	u32 used = 0;
	u32 start = s_fountIndex;
	if (s_pausedStations == 0 && !s_sendUnpause) {
		bool chunkReliable = false;
		*reliable = false;
		int destination = -1;
		if (s_chunkLength + 9 < size) {
			u32 length;
			do {
				if (s_chunkLength != 0) {
					packet[0] = s_chunkChannel;
					*(u32 *)(packet + 1) = s_chunkNode;
					*(u32 *)(packet + 5) = s_chunkLength;
					memcpy(packet + 9, s_chunk, s_chunkLength);
					used += s_chunkLength + 9;
					packet += s_chunkLength + 9;
					s_chunksSent[s_fountIndex]++;
					s_bytesSent[s_fountIndex] += used;
				}
				DataFount fount = s_founts[s_fountIndex];
				length = fount ? fount(s_chunk, &s_chunkChannel, &s_chunkNode, size - 5, &chunkReliable) : 0;
				s_chunkLength = length;
				if (chunkReliable)
					*reliable = true;
				if (destination == -1)
					destination = s_chunkNode;
				else if (destination != s_chunkNode)
					destination = 0xFFFF;
			} while ((length != 0 || (s_fountIndex = (s_fountIndex + 1) % 3) != start)
			         && length + used + 9 < size);
			if (destination != -1)
				*node = destination;
		}
		return used;
	}
	for (u32 station = 0; station < 11; station++)              // stations gone are no longer waited for
		if ((s_pausedStations & 1 << station) && !Session::nodeIsConnected(Session::convertIdPiaToVitei(station)))
			s_pausedStations ^= 1 << station;
	if (size - 5 > 7) {
		u32 me = Session::convertIdViteiToPia(Session::getNodeID());
		if (!(s_pausedStations & 1 << me) && (s_pauseResend < 1 || (s_pauseResend--, s_sendUnpause))) {
			*reliable = true;
			PauseNotification notification = {PAUSE_NOTIFICATION_HDR, s_pausedStations};
			s_pauseResend = 30;
			s_sendUnpause = false;
			packet[0] = 0;
			*(u32 *)(packet + 1) = 0xFFFF;
			*(u32 *)(packet + 5) = sizeof notification;
			memcpy(packet + 9, &notification, sizeof notification);
			used = 9 + sizeof notification;
		}
	}
	return used;
}

// 0x0010771C (Network's data listener): each chunk addressed to this console or to everybody goes to its
// channel's listener, with the sender's node id.
static void dataListenerRoute(const u8 *packet, u32 length, u32, u32 sourceNode)
{
	u32 me = Session::getNodeID();
	while (length != 0) {
		u8 channel = packet[0];
		u32 node = *(u32 *)(packet + 1);
		u32 size = *(u32 *)(packet + 5);
		if ((node == me || node == 0xFFFF) && s_listeners[channel] != nullptr)
			s_listeners[channel](packet + 9, size, channel, sourceNode);
		packet += 9 + size;
		length -= 9 + size;
	}
}
// "[datarouter::dataListenerRoute] Port %d not registered with data router!" (0x00354DC8) was the log of
// a chunk without listener: the log is gone, the chunk is skipped.

// ---- the network pause ---------------------------------------------------------------------------------

// 0x001077D0 (channel 0): "Received paused status: 0x%x. Current status is 0x%x". A station is ready once
// any console says so; when the last one is, this console tells the others at once.
static void pausedDataListener(const u8 *data, u32, u32, u32)
{
	const PauseNotification *notification = (const PauseNotification *)data;
	// "Header 0x%x does not match PAUSE_NOTIFICATION_HDR 0x%x" (a log only: the data is used anyway)
	s_pausedStations &= notification->pausedStations;
	if (notification->pausedStations != 0 && s_pausedStations == 0)
		s_sendUnpause = true;
}

// 0x001763A4: the battle pauses: every station present is paused. "Sending paused status: 0x%x".
void DataRouter::pauseOutgoing()
{
	s_pausedStations = 0;
	for (u32 station = 0; station < 11; station++)
		if (Session::nodeIsConnected(Session::convertIdPiaToVitei(station)))
			s_pausedStations |= 1 << station;
}

void DataRouter::clearPausedStatus() { s_pausedStations = 0; }              // 0x00176410

// 0x00176424: this console is ready to go on. "Unpausing.  Current paused status is 0x%x".
void DataRouter::setReadyToUnpause()
{
	s_pausedStations ^= 1 << Session::convertIdViteiToPia(Session::getNodeID());
}

bool DataRouter::allUnitsReadyToUnpause() { return s_pausedStations == 0; }  // 0x001764B0
