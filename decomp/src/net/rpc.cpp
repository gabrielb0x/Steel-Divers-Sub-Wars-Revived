// source/net/rpc.cpp (rpc.o): the scripts' remote calls. A script calls a public function of a script, or of
// a synced actor, on another console (natives netCallPublic, netCallPublicf, actorSyncCallPublic...:
// amxnet.cpp, amxactor.cpp); the call travels as a DataStreamer message (channel 1) and runs there in the
// next frame. When it cannot run (no such script or function), it is tried again for 20 frames, then the
// caller's "<function>_err" public, if it has one, is called back with the node that failed.
//
// Reconstructed by hand from decomp/raw/source/net/rpc.cpp and the disassembly. Not compilable on its own.

// A call (0xA0 bytes), sent as it is, followed by the bytes of its string and array arguments:
struct RpcCall {
	int origin;                         // +0x00 a script call: the caller's UID (-1: no error callback);
	                                    //       an actor call: the node owning the actor
	u32 uid;                            // +0x04 the script (0: the observer, amxSysObserverUID) or the
	                                    //       actor's sync id
	char name[32];                      // +0x08 the public function
	u32 count;                          // +0x28 arguments
	cell args[26];                      // +0x2C values; for a string its length, for an array the length
	                                    //       (the argument that follows it)
	u32 strings;                        // +0x94 bit per argument: a string
	u32 arrays;                         // +0x98 bit per argument: an array
	bool toActor;                       // +0x9C
	bool hasErrorCallback;              // +0x9D the caller has "<name>_err"
};

// Calls waiting to be sent (0x00567100, 192 entries of 0xAC bytes).
struct OutgoingCall {
	u32 node;                           // +0x00 addressee
	RpcCall call;                       // +0x08
	u8 *extra;                          // +0xA8 its strings and arrays, in s_extra
};
static OutgoingCall s_outgoing[192];
static u32 s_outgoingCount;             // 0x0038E7A0
static u8 s_extra[0x400];               // 0x0056F200 strings and arrays of the waiting calls
static u32 s_extraUsed;                 // 0x0038E7A4
static u32 s_frames;                    // 0x0038E7A8 processQueue calls (read by nothing)
static u8 s_packet[0x4A0];              // 0x0052EB60 one call and its data, as sent

// Calls received (0x0052F000, 192 entries of 0x4AC bytes), kept in a list (newest first).
struct IncomingCall {
	bool used;                          // +0x000
	u8 tries;                           // +0x001 frames left to find its function: 20, 1 for an "_err"
	u32 source;                         // +0x004 sender's node
	RpcCall call;                       // +0x008
	u8 extra[0x400];                    // +0x0A8
	IncomingCall *next;                 // +0x4A8
};
static IncomingCall s_incoming[192];
static IncomingCall *s_incomingList;    // 0x0038E7AC

// 0x00252B88
void RPC::clear()
{
	DataStreamer::clear();
	for (IncomingCall &c : s_incoming)
		c.used = false;
	s_incomingList = nullptr;
	s_outgoingCount = 0;
	s_extraUsed = 0;
}

void RPC::registerListeners() { DataStreamer::registerListener(amxDataRecvCB, 1); }   // 0x002DC668

// ---- calling ------------------------------------------------------------------------------------------

// 0x001DAAE8: amx's native with its format ("a" array, "s" string, anything else: a value by reference),
// for a script (uid) or an actor of this console (toActor: uid is its sync id). Outside a network session
// the call runs at once, on this console (values only). Otherwise it is queued for `node`.
void RPC::callPublic(AMX *amx, int callerUid, u32 uid, const char *name, const char *format, const cell *params,
                     u32 count, bool toActor, u32 node)
{
	AMXLoader *target = nullptr, *caller = nullptr;
	if (!toActor) {
		target = AMXLoader::uidToAmx(uid);
		if (callerUid >= 0)
			caller = AMXLoader::uidToAmx(callerUid);
	} else if (Actor *actor = SyncList::actorGetFromID(Session::getNodeID(), uid)) {
		target = actor->script;                                        // +0x110
		if (callerUid >= 0)
			caller = target;
	}
	if (!Network::isActive()) {
		int index;
		if (target == nullptr || (index = target->findPublic(name)) < 0)
			return;
		AMXState state;
		target->freezeState(&state);
		for (u32 i = count; i-- > 0;)
			target->pushArg(*amx->getAddr(params[i]));                 // vtable +0x2C
		target->callFunction(index);
		target->thawState(&state);
		return;
	}
	RpcCall call = {};
	call.toActor = toActor;
	call.uid = uid;
	call.origin = callerUid;
	strcpy(call.name, name);
	call.count = count;
	u8 *extra = nullptr;
	char string[384];
	for (int i = count - 1; i >= 0; i--) {
		if (format[i] == 'a') {
			if ((u32)i < count - 1) {                                  // its length is the next argument
				if (extra == nullptr)
					extra = s_extra + s_extraUsed;
				const void *array = amx->getAddr(params[i]);
				call.args[i] = call.args[i + 1];
				call.arrays |= 1 << i;
				if (call.args[i] > 0) {
					// over 0x3FF: "Trying to write %d bytes to the string buffer; used %d; %d bytes left!"
					memcpy(s_extra + s_extraUsed, array, call.args[i]);
					s_extraUsed += call.args[i];
				}
			}
		} else if (format[i] == 's') {
			if (extra == nullptr)
				extra = s_extra + s_extraUsed;
			amx->getString(string, params[i]);                          // vtable +0x30
			call.args[i] = strlen(string);
			call.strings |= 1 << i;
			if (call.args[i] > 0) {
				memcpy(s_extra + s_extraUsed, string, call.args[i]);
				s_extraUsed += call.args[i];
			}
		} else {
			call.args[i] = *amx->getAddr(params[i]);
		}
	}
	if (caller != nullptr) {
		char error[36];
		sprintf(error, "%s%s", call.name, "_err");
		call.hasErrorCallback = caller->findPublic(error) >= 0;
	}
	if (s_outgoingCount >= 192)
		return;                                                        // "Too many RPC calls: %s!"
	OutgoingCall &out = s_outgoing[s_outgoingCount++];
	out.extra = extra;
	out.node = node;
	out.call = call;
}

// ---- every frame (main loop) ---------------------------------------------------------------------------

// 0x0010B614: runs the calls received, then sends the calls queued (as many as DataStreamer takes this
// frame, the rest waits).
void RPC::processQueue()
{
	IncomingCall *list = s_incomingList;
	s_incomingList = nullptr;
	IncomingCall **link = &list;
	while (IncomingCall *in = *link) {
		RpcCall &c = in->call;
		u32 uid = c.uid;
		if (uid == 0 && !c.toActor)
			uid = amxSysObserverUID();
		bool isError = strstr(c.name, "_err") != nullptr;
		AMXLoader *target = nullptr;
		if (!c.toActor)
			target = AMXLoader::uidToAmx(uid);
		else if (!isError || Session::getNodeID() == (u32)c.origin)
			if (Actor *actor = SyncList::actorGetFromID(c.origin, uid))
				target = actor->script;
		int index;
		bool called = false;
		if (target != nullptr && (index = target->findPublic(c.name)) >= 0) {
			// "[RPC::processQueue] call AMX function. funcName: %s"
			AMXState state;
			target->freezeState(&state);
			const u8 *extra = in->extra;
			for (u32 i = c.count; i-- > 0;) {
				bool isString = c.strings >> i & 1, isArray = c.arrays >> i & 1;
				if (!isString && !isArray) {
					target->pushArg(c.args[i]);
					continue;
				}
				cell buffer[8];
				u32 length = c.args[i];
				if (isString ? length > 31 : length > 32)
					length = isString ? 31 : 32;       // "String/Array of length greater than %d pushed; truncating"
				memcpy(buffer, extra, length);
				extra += length;
				if (isArray) {
					target->pushArgArray(buffer, length);
				} else {
					((char *)buffer)[length] = 0;
					target->pushArgString((char *)buffer);
				}
			}
			target->callFunction(index);
			target->thawState(&state);
			called = true;
		} else if (--in->tries != 0) {
			link = &in->next;                              // kept for the next frame
			continue;
		}
		// Given up: the caller's "<name>_err"(node) on the sending console.
		if (!called && !isError && c.hasErrorCallback && (c.toActor || c.origin >= 0)) {
			RpcCall reply = {};
			if (!c.toActor) {
				reply.origin = uid;
				reply.uid = c.origin;
			} else {
				reply.origin = c.origin;
				reply.uid = uid;
			}
			reply.toActor = c.toActor;
			sprintf(reply.name, "%s%s", c.name, "_err");
			reply.count = 1;
			reply.args[0] = Session::getNodeID();
			DataStreamer::queueData((u8 *)&reply, sizeof reply, 1, in->source);
		}
		in->used = false;
		*link = in->next;
	}
	*link = s_incomingList;                                // what arrived meanwhile
	s_incomingList = list;

	u32 sent = 0;
	for (u32 i = 0; i < s_outgoingCount; i++) {
		OutgoingCall &out = s_outgoing[i];
		memcpy(s_packet, &out.call, sizeof(RpcCall));
		u32 size = sizeof(RpcCall);
		const u8 *extra = out.extra;
		if (extra != nullptr) {
			for (u32 a = 0; a < out.call.count; a++) {
				u32 n;
				if ((out.call.arrays >> a & 1) && a < out.call.count - 1)
					n = out.call.args[a + 1];
				else if (out.call.strings >> a & 1)
					n = out.call.args[a];
				else
					continue;
				if (size + n <= 0x4A0) {   // "Including data/strings makes packet too big; skipping ..."
					memcpy(s_packet + size, extra, n);
					extra += n;
					size += n;
				}
			}
		}
		if (DataStreamer::sendBufferAvailable() < size)
			break;
		DataStreamer::queueData(s_packet, size, 1, out.node);
		sent++;
		if (out.extra != nullptr && size > sizeof(RpcCall)) {      // its data leaves s_extra
			u32 used = size - sizeof(RpcCall);
			memmove(out.extra, extra, s_extraUsed - used - (out.extra - s_extra));
			s_extraUsed -= used;
			for (u32 j = 0; j < s_outgoingCount; j++)
				if (s_outgoing[j].extra > out.extra)
					s_outgoing[j].extra -= used;
		}
	}
	s_outgoingCount -= sent;
	memcpy(&s_outgoing[0], &s_outgoing[sent], s_outgoingCount * sizeof(OutgoingCall));
	s_frames++;
}

// 0x0017189C (DataStreamer listener, channel 1): a call received is kept for processQueue. (192 calls at
// most; the search for a free entry has no fallback.)
static void amxDataRecvCB(const u8 *data, u32 length, u8, u32 source)
{
	IncomingCall *in = nullptr;
	for (IncomingCall &c : s_incoming) {
		if (!c.used) {
			in = &c;
			break;
		}
	}
	in->source = source;
	in->used = true;
	memcpy(&in->call, data, sizeof(RpcCall));
	memcpy(in->extra, data + sizeof(RpcCall), length - sizeof(RpcCall));
	in->tries = strstr(in->call.name, "_err") == nullptr ? 20 : 1;
	in->next = s_incomingList;
	s_incomingList = in;
}
