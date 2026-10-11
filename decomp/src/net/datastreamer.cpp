// source/net/datastreamer.cpp (datastreamer.o): messages of any size (up to 32 blocks of 1,308 bytes) sent
// reliably to one console or to all: the scripts' remote calls (rpc.cpp, channel 1), and the players' Miis
// (facesystem.cpp, channel 5). A message is cut into blocks, each block scrambled and checked by a CRC-32,
// and put back together on arrival.
//
// Reconstructed by hand from decomp/raw/source/net/datastreamer.cpp and the disassembly. Not compilable on its
// own. Two mutexes guard the queues (the sending side, the receiving side): Pia's receive callbacks and the
// main loop both use them.
//
// A block on the wire (DataRouter channel 1, 2 or 5):
//   u32 seed        rand() of the sender
//   u32 crc         CRC-32 (zlib's) of what follows, data included (scrambled)
//   u8  index       of the block in its message
//   u8  count       blocks in the message
//   u16 length      of this block's data (at most 0x51C)
//   u32 message     the sender's message counter
//   u8  data[length]
// The data is XORed with the low bytes of rand() after srand(seed ^ 0x71946284), byte after byte. rand() is
// the ARM C library's (0x0023F4FC): an additive generator of 55 words, srand(x) filling them from the last
// to the first with x + (x >> 16), x = x * 0x10DCD + 0x66D619E1; rand() adds word k (31 ahead) to word j,
// stores it, moves both on, and returns the sum & 0x7FFFFFFF. (Checked against the game's own code.)
// After each block the generator is seeded again with the time (System::getTime), so that the game's other
// uses of rand() do not follow the network.
// The receiver checks the CRC before anything else, but not `length` against the size of what it received.
// Three of datastreamer.o's strings have lost their code (their logs were in the receiving side): "Too many
// incoming blocks!  Send less data or increase MAX_INCOMING_BLOCKS", "Not enough space in the buffer to
// handle all incoming data!", "Trying to receive a file composed of too many chunks!".

struct StreamListener {
	void (*callback)(const void *data, u32 length, u8 channel, u32 sourceNode);
	u8 channel;
};

struct OutgoingBlock {                  // 0x534 bytes
	u8 channel;                         // +0x00
	u32 node;                           // +0x04 the addressee (0xFFFF: everybody)
	u32 seed;                           // +0x08 from here on: what is sent (0x10 + length bytes)
	u32 crc;                            // +0x0C
	u8 index, count;                    // +0x10
	u16 length;                         // +0x12
	u32 message;                        // +0x14
	u8 data[0x51C];                     // +0x18
};

struct IncomingMessage {                // 0x18 bytes: a message whose blocks are arriving
	u32 source;                         // +0x00 sender's node id
	u32 message;                        // +0x04
	u8 channel;                         // +0x08
	u8 count;                           // +0x09
	u32 received;                       // +0x0C bit per block
	u32 firstSlot;                      // +0x10 its blocks: slots firstSlot..firstSlot+count-1
	u32 lastSender;                     // +0x14
};

struct BlockSlot {                      // 0x51E bytes
	u16 length;
	u8 data[0x51C];
};

struct DataStreamerData {               // 0x17C9E8 bytes (1.5 MB), new'd once by init
	StreamListener listeners[10];       // +0x000000
	u32 listenerCount;                  // +0x000050
	OutgoingBlock queue[128];           // +0x000054 blocks waiting to be sent
	u32 queued;                         // +0x029A54
	BlockSlot slots[1024];              // +0x029A58 blocks received
	u32 slotsUsed;                      // +0x171258
	u8 message[32 * 0x51C];             // +0x17125C a complete message, handed to the listeners
	IncomingMessage incoming[128];      // +0x17B5DC
	u32 incomingCount;                  // +0x17C1DC
	struct { u32 source, message; } done[256];  // +0x17C1E0 the last 256 messages completed
	u32 doneNext;                       // +0x17C9E0
	u32 lastCrc;                        // +0x17C9E4 the last block received (the same block twice: ignored)
};

static DataStreamerData *s;             // 0x0038E718
static u32 s_blocksSent;                // 0x0038E71C debug count (dbgSentClear)
static u32 s_nextMessage;               // 0x0038E720 wraps after 0x0FFFFFFF
static nn::os::Mutex s_sendMutex;       // 0x0038E724
static nn::os::Mutex s_receiveMutex;    // 0x0038E728

static void scramble(u8 *data, u32 length, u32 seed)
{
	srand(seed ^ 0x71946284);
	for (u32 i = 0; i < length; i++)
		data[i] ^= (u8)rand();
	srand(System::getTime());
}

// 0x00108EF0
void DataStreamer::init()
{
	s = new DataStreamerData;
	clear();
	s_sendMutex.Initialize();
	s_receiveMutex.Initialize();
	DataRouter::registerDataFount(dataFount);
	DataRouter::registerDataListener(dataListener, 1);
	DataRouter::registerDataListener(dataListener, 2);
	DataRouter::registerDataListener(dataListener, 5);
	Session::registerNotifyCB(datastreamerSessionNotifyCB);
}

// 0x0011139C (also inlined in init): every queue empty, no message completed.
void DataStreamer::clear()
{
	s->listenerCount = 0;
	s->queued = 0;
	s->slotsUsed = 0;
	s->incomingCount = 0;
	s->doneNext = 0;
	s->lastCrc = 0;
	for (auto &d : s->done)
		d.source = d.message = 0xFFFFFFFF;
}

// 0x0017AB48: RPC (channel 1) and FaceSystem (channel 5).
void DataStreamer::registerListener(void (*callback)(const void *, u32, u8, u32), u8 channel)
{
	s->listeners[s->listenerCount].callback = callback;
	s->listeners[s->listenerCount].channel = channel;
	s->listenerCount++;
}

void DataStreamer::dbgSentClear() { s_blocksSent = 0; }        // 0x00101C48

// 0x00111368: bytes that can be queued now (32 blocks at most).
u32 DataStreamer::sendBufferAvailable()
{
	u32 blocks = min(128 - s->queued, 32u);
	return blocks * 0x51C;
}

// ---- sending -------------------------------------------------------------------------------------------

// 0x002436EC: queues a message for a node (0xFFFF: every console). A message for this console, or for
// everybody, also goes at once to this console's own listeners. False when the queue has no room.
// "[DataStreamer::queueData] dataLen = %d, numChunks = %d, myNodeID = %x, destNodeID = %x,
// shouldSendRemotely = %d", "shouldSendLocally = %d", "Sent %d chunks!", "Sent to %d listeners!".
bool DataStreamer::queueData(const u8 *data, u32 length, u8 channel, u32 node)
{
	if (length == 0)
		return false;
	u32 blocks = (length + 0x51B) / 0x51C;
	u32 me = Session::getNodeID();
	if (node != me) {
		s_sendMutex.Lock();
		if (blocks > sendBufferAvailable() / 0x51C) {
			s_sendMutex.Unlock();
			return false;
		}
		if (s_nextMessage > 0x0FFFFFFE)
			s_nextMessage = 0;
		// (a check that `blocks` blocks hold the message, always true, logs otherwise "Trying to send length
		// %d but only managed to send length %d!  Leave for next frame")
		u32 message = s_nextMessage++;
		for (u32 i = 0; i < blocks; i++) {
			OutgoingBlock &b = s->queue[s->queued + i];
			u32 size = min(length - i * 0x51C, 0x51Cu);
			b.channel = channel;
			b.node = node;
			b.index = i;
			b.count = blocks;
			memcpy(b.data, data + i * 0x51C, size);
			b.message = message;
			b.length = size;
			b.seed = rand();
			scramble(b.data, b.length, b.seed);
			b.crc = generateCRC(&b.index, b.length + 8);
		}
		s->queued += blocks;
		s_sendMutex.Unlock();
	}
	if (node == me || node == 0xFFFF)
		for (u32 i = 0; i < s->listenerCount; i++)
			if (s->listeners[i].channel == channel)
				s->listeners[i].callback(data, length, channel, me);
	return true;
}

// 0x00110E24 (a DataRouter fount): one block per call, sent reliably. The router calls it again while the
// packet has room. (It does not look at the room it is given.)
static u32 dataFount(u8 *out, u8 *channel, u32 *node, u32, bool *reliable)
{
	s_sendMutex.Lock();
	if (s->queued == 0) {
		s_sendMutex.Unlock();
		return 0;
	}
	OutgoingBlock &b = s->queue[0];
	u32 size = b.length + 0x10;
	memcpy(out, &b.seed, size);
	*channel = b.channel;
	*node = b.node;
	s_blocksSent++;
	if (--s->queued != 0)
		memcpy(&s->queue[0], &s->queue[1], s->queued * sizeof(OutgoingBlock));
	s_sendMutex.Unlock();
	*reliable = true;
	return size;
}

// 0x00101C5C: after the frame's two sends (main.cpp), the blocks that found no room are dropped: the
// queue starts every frame empty.
void DataStreamer::update()
{
	s_sendMutex.Lock();
	s->queued = 0;                       // (one block at a time, from the last)
	s_sendMutex.Unlock();
}

// ---- receiving -----------------------------------------------------------------------------------------

// 0x0010F878 (DataRouter channels 1, 2, 5): a block. Corrupt or repeated blocks are ignored; a message
// complete goes to the listeners of its channel, with its sender's node id.
static void dataListener(const u8 *packet, u32 size, u8 channel, u32 source)
{
	if (size < 9 || size > 0x52C)
		return;                          // "Received data of invalid length %db on port %d! Ignoring"
	struct {
		u32 seed, crc;
		u8 index, count;
		u16 length;
		u32 message;
		u8 data[0x528];
	} b;
	memcpy(&b, packet, size);
	if (b.crc != generateCRC(&b.index, b.length + 8))
		return;                          // "Corrupt data received on port %d! id 0x%p"
	scramble(b.data, b.length, b.seed);
	s_receiveMutex.Lock();
	if (s->lastCrc == b.crc)
		goto done;
	s->lastCrc = b.crc;
	for (auto &d : s->done)
		if (d.message == b.message && d.source == source)
			goto done;                   // a message already complete
	int found = -1;
	for (u32 i = 0; i < s->incomingCount; i++) {
		IncomingMessage &m = s->incoming[i];
		if (m.message == b.message && m.source == source && m.channel == channel)
			found = i;
	}
	if (found < 0) {
		if (s->slotsUsed + b.count >= 0x400)
			goto done;
		found = initIncomingBlock(&b, channel, source);
	}
	{
		IncomingMessage &m = s->incoming[found];
		if (m.received & 1 << b.index)
			goto done;
		m.received |= 1 << b.index;
		BlockSlot &slot = s->slots[m.firstSlot + b.index];
		slot.length = b.length;
		memcpy(slot.data, b.data, b.length);
		m.lastSender = source;
		if (m.received != (1u << m.count) - 1)
			goto done;
		s->done[s->doneNext].source = source;
		s->done[s->doneNext].message = m.message;
		if (++s->doneNext > 0xFF)
			s->doneNext = 0;
		u16 total = 0;
		for (int i = 0; i < m.count; i++) {
			BlockSlot &part = s->slots[m.firstSlot + i];
			memcpy(s->message + total, part.data, part.length);
			total += part.length;
		}
		for (u32 i = 0; i < s->listenerCount; i++)
			if (s->listeners[i].channel == channel)
				s->listeners[i].callback(s->message, total, channel, m.lastSender);
		clearIncomingBlock(found);
	}
done:
	s_receiveMutex.Unlock();
}

// 0x0011B3B0: a new message: its blocks get the next `count` slots.
static int initIncomingBlock(const void *block, u8 channel, u32 source)
{
	const u8 count = ((const u8 *)block)[9];
	IncomingMessage &m = s->incoming[s->incomingCount++];
	m.source = source;
	m.message = *(const u32 *)((const u8 *)block + 12);
	m.count = count;
	m.received = 0;
	m.lastSender = 0;
	m.firstSlot = s->slotsUsed;
	m.channel = channel;
	s->slotsUsed += count;
	return s->incomingCount - 1;
}

// 0x0011B434: forgets a message and gives its slots back (the later messages' blocks move down).
static void clearIncomingBlock(int index)
{
	IncomingMessage gone = s->incoming[index];
	for (u32 i = 0; i < s->incomingCount; i++) {
		IncomingMessage &m = s->incoming[i];
		if (m.message == gone.message && m.channel == gone.channel && m.source == gone.source) {
			if (i >= s->incomingCount - 1) {
				s->incomingCount--;
				break;
			}
			memcpy(&s->incoming[i], &s->incoming[i + 1], (s->incomingCount - i - 1) * sizeof(IncomingMessage));
			s->incomingCount--;
		}
		if (s->incoming[i].firstSlot > gone.firstSlot) {
			memcpy(&s->slots[s->incoming[i].firstSlot - gone.count], &s->slots[s->incoming[i].firstSlot],
			       s->incoming[i].count * sizeof(BlockSlot));
			s->incoming[i].firstSlot -= gone.count;
		}
	}
	s->slotsUsed -= gone.count;
}

// 0x00110D50 (Session notify, NODE_QUIT: a node left): its messages, complete or not, are forgotten.
static void datastreamerSessionNotifyCB(int code, u32 node)
{
	if (code != NODE_QUIT)
		return;
	for (auto &d : s->done)
		if (d.source == node)
			d.source = d.message = 0xFFFFFFFF;
	for (int i = s->incomingCount - 1; i >= 0; i--)
		if (s->incoming[i].source == node)
			clearIncomingBlock(i);
}
