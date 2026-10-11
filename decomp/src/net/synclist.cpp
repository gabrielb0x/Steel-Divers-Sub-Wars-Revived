// source/net/synclist.cpp (synclist.o): the synced actors. An actor owned by a console (its own submarine,
// its torpedoes...) has some of its properties copied to the other consoles every frame; there, a copy of
// the actor (registered as remote, with the property "synced" = 1) receives them. Pawn chooses what is
// synced (natives actorSync..., amxactor.cpp; sync_legacy.inc in the scripts).
//
// Reconstructed by hand from decomp/raw/source/net/synclist.cpp and the disassembly. Not compilable on its
// own.
//
// A packet (DataRouter channel 3, unreliable, to everybody), once per frame (prime() then the send):
//   u16 sequence, u16 sequence2    two counters, the second started at 0x8000: a packet is newer when
//                                  either counter is greater, so the wrap of one does not lose packets
//   u8  station                    the sender's Pia station
//   then for each actor this console owns that has synced properties:
//     u16 id, u8 size              the actor's sync id (per owner) and the size of its properties
//     the properties' values, in the order of the owner's list (BXML dynamic attributes: byte, char,
//     short, int or float arrays)

struct SyncedActor {                    // 0x14 bytes, 261 of them (0x0056F898)
	bool used;                          // +0x00
	u8 id;                              // +0x01 sync id, unique per owner
	u8 station;                         // +0x02 the owner's Pia station
	Actor *actor;                       // +0x04
	PropertyNode *properties;           // +0x08
	u8 size;                            // +0x0C bytes of all its synced properties
	SyncedActor *next;                  // +0x10
};

struct PropertyNode {                   // 0x80 bytes, 1044 of them (0x00570CFC)
	bool used;                          // +0x00
	BXML::DynamicAttribute attribute;   // +0x04 (name +0x0C, data +0x14, size +0x18)
	PropertyNode *next;                 // +0x7C
};

// ---- module state --------------------------------------------------------------------------------------
static bool s_active;                   // 0x0038E828 receiving (setActive)
static bool s_primed;                   // 0x0038E829 send this frame (prime)
static SyncedActor *s_list;             // 0x0038E82C newest first
static u8 s_nextId;                     // 0x0038E830 registerActor
static u32 s_ownCount;                  // 0x0038E834 actors of this console in the list
static BXML::DynamicAttribute *s_synced;// 0x0038E838 "synced" = 1, set on every remote copy
static u16 s_sequence, s_sequence2;     // 0x0038E848, 0x0038E84A
static u16 s_lastSequence[8][2];        // 0x005916FC per station: the newest packet received
static SyncedActor s_actors[261];
static PropertyNode s_nodes[1044];

static u8 myStation() { return Session::convertIdViteiToPia(Session::getNodeID()); }

// 0x00106144
void SyncList::init()
{
	clear();
	{
		ScopedHeap heap(System::getSysHeap());
		s_synced = new BXML::DynamicAttribute("synced");
	}
	DataRouter::registerDataListener(syncDataRecvCB, 3);
	DataRouter::registerDataFount(syncDataSendCB);
	int one = 1;
	s_synced->setIntData(&one, 1);
}

// 0x0010DD98
void SyncList::clear()
{
	for (SyncedActor &a : s_actors)
		a = {};
	for (PropertyNode &n : s_nodes) {
		n.used = false;
		n.next = nullptr;
	}
	s_list = nullptr;
	s_nextId = 0;
	s_ownCount = 0;
	memset(s_lastSequence, 0, sizeof s_lastSequence);
	s_sequence = 0;
	s_sequence2 = 0x8000;
}

void SyncList::prime() { s_primed = true; }                  // 0x001061E0, every frame in a session
void SyncList::setActive(bool active) { s_active = active; } // 0x002F4A44

// ---- the list ------------------------------------------------------------------------------------------

// 0x00174540: "num outgoing syncs += %d:%s (total %d)" for this console's actors, "num incoming syncs from
// [%x] += %d:%s (total %d)" for the others'.
static SyncedActor *registerActorExplicit(Actor *actor, u32 owner, u8 id)
{
	// (a search for the actor already in the list, whose result is unused: "Registering actor 0x%x
	// controller 0x%x sync id %d -- already exists! Was c 0x%x id %d" was its log)
	SyncedActor *a = nullptr;
	for (SyncedActor &free : s_actors) {
		if (!free.used) {
			a = &free;
			a->used = true;
			break;
		}
	}
	a->station = Session::convertIdViteiToPia(owner);
	a->id = id;
	a->actor = actor;
	a->next = s_list;
	s_list = a;
	s_ownCount = 0;
	for (SyncedActor *b = s_list; b != nullptr; b = b->next)
		if (b->station == myStation())
			s_ownCount++;
	return a;
}

// 0x002F473C: an actor of this console.
SyncedActor *SyncList::registerActor(Actor *actor) { return registerActorExplicit(actor, Session::getNodeID(), s_nextId++); }

// 0x002F4A00: the copy of another console's actor (sync_legacy.inc's @worldSpawnActorRemote).
SyncedActor *SyncList::registerActorRemote(Actor *actor, u32 owner, u8 id)
{
	actor->setAttribute(s_synced, false);                        // vtable +0x04
	return registerActorExplicit(actor, owner, id);
}

static void freeEntry(SyncedActor *a)
{
	for (PropertyNode *n = a->properties, *next; n != nullptr; n = next) {
		next = n->next;
		n->used = false;
		n->next = nullptr;
	}
	*a = {};
}

// 0x002F44E8: "num outgoing/incoming syncs -= ..."
void SyncList::removeActor(Actor *actor)
{
	SyncedActor **link = &s_list;
	while (*link != nullptr && (*link)->actor != actor)
		link = &(*link)->next;
	SyncedActor *a = *link;
	if (a == nullptr)
		return;
	*link = a->next;
	s_ownCount = 0;
	for (SyncedActor *b = s_list; b != nullptr; b = b->next)
		if (b->station == myStation())
			s_ownCount++;
	freeEntry(a);
}

// 0x002F476C: adds a property to the synced ones of an actor (once), with its current value.
// "Trying to sync property %s on unsynced actor!", "%s Tried to sync a property %s before we've defined it!"
bool SyncList::actorSyncProperty(Actor *actor, const char *name)
{
	SyncedActor *a = s_list;
	while (a != nullptr && a->actor != actor)
		a = a->next;
	if (a == nullptr)
		return false;
	BXML::DynamicAttribute probe(name);
	actor->getAttribute(&probe);                                 // vtable +0x08
	for (PropertyNode *n = a->properties; n != nullptr; n = n->next)
		if (strcmp(n->attribute.name, name) == 0)
			return true;
	PropertyNode *node = nullptr;
	for (PropertyNode &free : s_nodes) {
		if (!free.used) {
			node = &free;
			node->used = true;
			break;
		}
	}
	node->attribute.setName(name);
	a->actor->getAttribute(&node->attribute);
	a->size += node->attribute.size;
	node->next = a->properties;
	a->properties = node;
	return true;
}

// 0x001DB184 / 0x002F46F8 / 0x002F49BC / 0x00243C08
u32 SyncList::actorGetID(Actor *actor)
{
	for (SyncedActor *a = s_list; a != nullptr; a = a->next)
		if (a->actor == actor)
			return a->id;
	return -1;
}

bool SyncList::actorIsSynced(Actor *actor)
{
	for (SyncedActor *a = s_list; a != nullptr; a = a->next)
		if (a->actor == actor)
			return true;
	return false;
}

u32 SyncList::actorGetController(Actor *actor)                  // the owner's node id, 0 if not synced
{
	for (SyncedActor *a = s_list; a != nullptr; a = a->next)
		if (a->actor == actor)
			return Session::convertIdPiaToVitei(a->station);
	return 0;
}

Actor *SyncList::actorGetFromID(u32 owner, u32 id)
{
	u8 station = Session::convertIdViteiToPia(owner);
	for (SyncedActor *a = s_list; a != nullptr; a = a->next)
		if (a->station == station && a->id == id)
			return a->actor;
	return nullptr;
}

// 0x00105E48, every frame: when this console's node id changed,
// its actors follow ("My ID has changed so updating actor %x->%x": the actor's @setNetUID(newId)); the
// actors of a console gone ("Removing actor owned by %x"), or that now carry this console's new id, are
// killed (@kill) and forgotten.
void SyncList::removeOrphanedActors()
{
	static u32 previous = Session::getNodeID();                   // (guard 0x0038E840, value 0x0038E844)
	u32 me = Session::getNodeID();
	bool changed = me != previous;
	SyncedActor **link = &s_list;
	while (SyncedActor *a = *link) {
		u32 owner = Session::convertIdPiaToVitei(a->station);
		if ((changed && owner == previous) || (owner == 0 && me != 0)) {
			a->station = Session::convertIdViteiToPia(me);
			if (AMXLoader *script = a->actor ? a->actor->script : nullptr) {
				int index = script->findPublic("@setNetUID");
				if (index >= 0) {
					AMXState state;
					script->freezeState(&state);
					script->pushArg(me);
					script->callFunction(index);
					script->thawState(&state);
				}
			}
		} else if ((changed && owner == me) || (owner != 0 && !Session::nodeIsConnected(owner))) {
			if (AMXLoader *script = a->actor ? a->actor->script : nullptr) {
				int index = script->findPublic("@kill");
				if (index >= 0) {
					AMXState state;
					script->freezeState(&state);
					script->callFunction(index);
					script->thawState(&state);
				}
			}
			*link = a->next;
			freeEntry(a);
			continue;
		}
		link = &a->next;
	}
	previous = me;
}

// ---- network -------------------------------------------------------------------------------------------

// 0x00107470 (DataRouter fount): the properties of every actor this console owns, unreliably, to everybody.
static u32 syncDataSendCB(u8 *out, u8 *channel, u32 *node, u32 size, bool *reliable)
{
	if (!s_primed)
		return 0;
	u32 needed = 0;
	for (SyncedActor *a = s_list; a != nullptr; a = a->next)
		if (a->station == myStation() && a->size != 0)
			needed += 3 + a->size;
	if (needed == 0)
		return 0;
	needed += 5;
	if (needed > size)
		return 0;                       // "Sync Data payload %d exceeds available space %d; skipping"
	*reliable = false;
	s_sequence++;
	s_sequence2++;
	*(u16 *)out = s_sequence;
	*(u16 *)(out + 2) = s_sequence2;
	out[4] = myStation();
	u8 *p = out + 5;
	for (SyncedActor *a = s_list; a != nullptr; a = a->next) {
		if (a->station != myStation() || a->size == 0)
			continue;
		*(u16 *)p = a->id;
		p[2] = a->size;
		p += 3;
		for (PropertyNode *n = a->properties; n != nullptr; n = n->next) {
			a->actor->getAttribute(&n->attribute);
			memcpy(p, n->attribute.data, n->attribute.size);
			p += n->attribute.size;
		}
	}
	*channel = 3;
	*node = 0xFFFF;
	s_primed = false;
	return needed;
}

// 0x001073E8 (DataRouter channel 3): only a packet newer than the last one from its sender is read.
static void syncDataRecvCB(const u8 *packet, u32 length, u8, u32)
{
	if (!s_active)
		return;
	u16 sequence = *(const u16 *)packet, sequence2 = *(const u16 *)(packet + 2);
	u8 station = packet[4];
	u16 *last = s_lastSequence[station];
	if (last[0] < sequence || last[1] < sequence2) {
		last[0] = sequence;
		last[1] = sequence2;
		for (const u8 *p = packet + 5; p < packet + length;)
			p = readActorFromBuffer(p, station);
	}
}

// 0x00110728: one actor's block. Unknown actors ("SYNC RECV FROM %x NO ACTOR %d") and blocks whose size is
// not the one expected ("%s: Mine is %db, Theirs is %db") are skipped; otherwise each property gets its
// value and is set on the actor (vtable +0x04).
static const u8 *readActorFromBuffer(const u8 *p, u8 station)
{
	u16 id = *(const u16 *)p;
	u8 size = p[2];
	const u8 *data = p + 3;
	for (SyncedActor *a = s_list; a != nullptr; a = a->next) {
		if (a->station != station || a->id != id)
			continue;
		// size 0: "Error in buffer at 0x%p.  %d"
		if (size != a->size && a->size != 0)
			return data + size;
		for (PropertyNode *n = a->properties; n != nullptr; n = n->next) {
			u32 bytes = n->attribute.size & 0xFF;
			switch (n->attribute.type & 0xFF) {
			case 2: n->attribute.setByteData(data, bytes); break;
			case 3: n->attribute.setCharData(data, bytes); break;
			case 4: n->attribute.setShortData(data, bytes / 2); break;
			case 5: n->attribute.setIntData(data, bytes / 4); break;
			case 7: n->attribute.setFloatData(data, bytes / 4); break;
			}
			a->actor->setAttribute(&n->attribute, false);
			data += bytes;
		}
		return p + 3 + size;
	}
	return data + size;
}
