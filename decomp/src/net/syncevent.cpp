// source/net/syncevent.cpp (syncevent.o): a barrier between the consoles of a session. Each console marks
// a "sync point"; once every console present has reached the same point, check() is true on all of them,
// until acknowledged. The natives netSyncEventPoint, netSyncEventCheck and netSyncEventAcknowledgeSync;
// mode_periscope (the battle) waits this way for everybody, giving up after 10 seconds.
//
// Reconstructed by hand from decomp/raw/source/net/syncevent.cpp and the disassembly. Not compilable on its
// own. ("dataRecieveCallback" is the developers' spelling.)

// ---- module state --------------------------------------------------------------------------------------
static bool s_send;                     // 0x0038E810 this console reached a point: tell the others
static int s_syncs;                     // 0x0038E814 points reached by everybody, not yet acknowledged
static int s_points[32];                // 0x0056F818 per Pia station: points it reached that are not
                                        // complete yet; -1: no such station

// When no station is at 0 any more (each present one reached at least one more point), a point is complete.
static void checkComplete()
{
	for (u8 i = 0; i < 32; i++)
		if (s_points[i] == 0)
			return;
	s_syncs++;
	for (int &points : s_points)
		if (points > 0)
			points--;
}

// 0x0010679C
void SyncEvent::init()
{
	DataRouter::registerDataListener(dataRecieveCallback, 4);
	DataRouter::registerDataFount(dataSendCallback);
	Session::registerNotifyCB(notifyCallback);
}

// 0x002F72B8: Session::create and Session::join start with no station.
void SyncEvent::reset()
{
	for (int &points : s_points)
		points = -1;
	s_send = false;
	s_syncs = 0;
}

// 0x002F71CC: "Established new sync point (I am %x)".
void SyncEvent::point()
{
	s_points[Session::convertIdViteiToPia(Session::getNodeID())]++;
	s_send = true;
	checkComplete();
}

bool SyncEvent::check() { return s_syncs > 0; }        // 0x002F71B0
void SyncEvent::acknowledgeSync() { s_syncs--; }       // 0x002F7194

// 0x001076C0 (DataRouter fount): a point is one byte, '*', sent reliably to everybody on channel 4.
static u32 dataSendCallback(u8 *out, u8 *channel, u32 *node, u32 size, bool *reliable)
{
	if (!s_send || size == 0)
		return 0;
	out[0] = '*';
	*channel = 4;
	*node = 0xFFFF;
	*reliable = true;
	s_send = false;
	return 1;
}

// 0x001078E4 (DataRouter channel 4): another console reached a point.
static void dataRecieveCallback(const u8 *, u32, u8, u32 source)
{
	s_points[Session::convertIdViteiToPia(source)]++;
	checkComplete();
}

// 0x00107358 (Session notify): a node that joins starts at 0, one that leaves is no longer waited for.
static void notifyCallback(int code, u32 node)
{
	u32 station = Session::convertIdViteiToPia(node);
	if (code == 1)
		s_points[station] = 0;
	else if (code == 2)
		s_points[station] = -1;
	checkComplete();
}
