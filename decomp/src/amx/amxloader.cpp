// source/amx/amxloader.cpp (amxloader.o): the script loaders.
//
// Reconstructed by hand from decomp/raw/source/amx/amxloader.cpp and the disassembly; the class
// layout is in ghidra/types.h (struct AMXLoader). Not compilable on its own.
//
// Every Pawn script runs in a loader: the mode script (main.cpp), one per scripted actor (in its
// ActorData), plus the HUD, cameras... The loaders form a list walked once per frame by runAll().
// A script runs until it executes `sleep` (AMX_ERR_SLEEP), keeps its registers (freezeState) and
// resumes there next frame; it is finished when main() returns or on any other error.
// Scripts talk to each other through public functions (sysCallPublic & co, by UID), messages
// (sysSendMessage -> @eventMessage), delayed calls (sysCallPublicDelayed) and observers
// (sysObserve / sysNotify).

enum { AMX_EXEC_MAIN = -1, AMX_EXEC_CONT = -2 };   // amx.h
enum { AMX_ERR_EXIT = 1, AMX_ERR_SLEEP = 12 };

// 0x0038DD48: number of scripts executing (nested when a native calls back into a script).
static u16 s_executing;
// 0x0038DD4C: ids given to public function names, see findPublic().
static int s_publicNameCount;
// 0x0038DD50: list of the loaded scripts, newest first.
AMXLoader *AMXLoader::s_first;
// 0x0038DD54: first loader ever constructed: the mode script's (static object of main.cpp).
AMXLoader *AMXLoader::s_main;
// 0x0038DD58: loaders constructed so far; gives each its `index`.
int AMXLoader::s_count;
// 0x0038DD60: thread-local slot holding the loader currently executing.
static nn::os::ThreadLocalStorage s_current;
// 0x003B4B14: ten threads, constructed here but used elsewhere (not identified yet).
static nn::os::Thread s_threads[10];

// Public function names get a global id (hash table of 4096 buckets, 0x003B4B64) so that each
// loader can cache the AMX index of a public by id instead of searching the script every call.
struct PublicName {
	char name[0x40];
	int id;             // +0x40
	PublicName *prev;   // +0x44
	PublicName *next;   // +0x48
};
static PublicName *s_publicNames[4096];

// Same hash as the engine globals (amxsys.cpp): h = h * 33 + c over the first 64 characters.
static u32 hashName(const char *name)
{
	char buffer[0x40];
	strncpy(buffer, name ? name : "", sizeof(buffer));
	u32 hash = 0;
	for (const char *c = buffer; *c; c++) {
		hash = hash * 33 + (u8)*c;
	}
	return hash & 0xFFF;
}

// ---- AMXLoader ------------------------------------------------------------------------------

// 0x002F4E6C: called when a script is (re)started, links the loader at the head of the list.
void AMXLoader::init()
{
	uid = -1;
	messagesWritten = 0;
	messagesRead = 0;
	finished = false;
	ignorePause = false;
	if (s_first) {
		s_first->prev = this;
	}
	prev = NULL;
	next = s_first;
	s_first = this;
	for (int i = 0; i < 16; i++) {
		delayed[i].frames = 0;
	}
}

// 0x002F4EF0
void AMXLoader::cleanup()
{
	finished = true;
	memset(observers, 0, sizeof(observers));
	lastObserver = 0;
	observerCount = 0;
	if (prev) {
		prev->next = next;
	} else {
		s_first = next;
	}
	if (next) {
		next->prev = prev;
	}
}

// 0x001061F4: when a mode ends.
void AMXLoader::cleanupAll()
{
	for (AMXLoader *loader = s_first; loader; loader = loader->next) {
		loader->cleanup();
	}
}

// 0x0010622C: when a mode starts.
void AMXLoader::resetStock()
{
	s_first = NULL;
	s_main = NULL;
	s_count = 0;
	s_unknown5C = 0;    // 0x0038DD5C, not read anywhere identified yet
}

// 0x0010624C: once per frame (nnMain), under the script mutex. Stops as soon as the mode script
// is finished; while the game is paused, only the scripts with ignorePause run.
void AMXLoader::runAll()
{
	bool paused = System::isPaused();
	for (AMXLoader *loader = s_first; loader; loader = loader->next) {
		if (s_main->finished) {
			return;
		}
		if (loader->enabled == 1 && (!paused || loader->ignorePause)) {
			static_cast<ScriptAMXLoader *>(loader)->run();
		}
	}
}

// 0x00117AD8: before a script's frame: due delayed calls, then the queued messages.
void AMXLoader::preExecute()
{
	s_executing++;
	Renderer::setActiveMask(rendererMask);

	AMXState state;
	for (int i = 0; i < 16; i++) {
		AMXDelayedCall &call = delayed[i];
		if (call.frames > 0 && --call.frames == 0) {
			if (depth > 1) {
				freezeState(&state);
			}
			for (int arg = call.argCount - 1; arg >= 0; arg--) {   // Pawn pushes the last argument first
				pushArg(call.args[arg]);
			}
			callFunction(call.function);
			if (depth > 1) {
				thawState(&state);
			}
		}
	}

	if (eventMessage >= 0) {
		if (depth > 1) {
			freezeState(&state);
		}
		while (messagesWritten != messagesRead) {
			AMXMessage &msg = messages[messagesRead++ % 8];
			pushArg(msg.value);
			pushArg(msg.message);
			pushArg(msg.sender);
			callFunction(eventMessage);       // @eventMessage(sender, message, value)
		}
		if (depth > 1) {
			thawState(&state);
		}
	}
}

// 0x00124630: the actor running this script (0 in the actor natives means this one).
void AMXLoader::setUserObj(bool hasActor, Actor *actor)
{
	this->actor = actor;
	this->hasActor = hasActor;
}

// 0x001249D0
void AMXLoader::setRendererMask(u32 mask)
{
	rendererMask = mask;
}

// 0x001DB160
int AMXLoader::getUID()
{
	return uid;
}

// 0x001DB444: three floats read from the script's memory (returned in s0-s2).
VEC3 AMXLoader::getVector3(cell amx_addr)
{
	return *(VEC3 *)getAddr(amx_addr, 0);
}

// 0x001DB478: actor id as passed by a script; 0 is the actor running the script.
Actor *AMXLoader::getActor(int actorId)
{
	if (actorId == 0) {
		return hasActor == 1 ? actor : NULL;
	}
	return g_world->getActor(actorId);
}

// 0x001DB4A4: the loader whose native is being called.
AMXLoader *AMXLoader::getCurrentLoader()
{
	return (AMXLoader *)s_current.GetValue();
}

// 0x002355E4
void AMXLoader::getName(char *dest)
{
	strncpy(dest, name, 0x180);
}

// 0x00252BC8: below 1000 a UID is an actor id (its script), otherwise the UID a script gave itself
// with sysSetUID(); the first match in the list wins.
AMXLoader *AMXLoader::uidToAmx(int uid)
{
	if (uid < 1000) {
		Actor *actor = g_world->getActor(uid);
		return actor ? actor->script : NULL;
	}
	for (AMXLoader *loader = s_first; loader; loader = loader->next) {
		if (loader->uid == uid) {
			return loader;
		}
	}
	return NULL;
}

// 0x002F4D14: sysNotify(event, ...): calls `event` in every script observing this one, with the
// same arguments (read from this script's memory, they are passed by reference).
void AMXLoader::notifyObservers(const char *event, cell *args, u32 count)
{
	for (AMXLoader *loader = s_first; loader; loader = loader->next) {
		if (!(observers[loader->index >> 3] & (1 << (loader->index & 7)))) {
			continue;
		}
		int function = loader->findPublic(event);
		if (function < 0) {
			continue;
		}
		AMXState state;
		if (loader->depth > 1) {
			loader->freezeState(&state);
		}
		for (int i = count - 1; i >= 0; i--) {
			loader->pushArg(*getAddr(args[i], 0));
		}
		loader->callFunction(function);
		if (loader->depth > 1) {
			loader->thawState(&state);
		}
	}
}

// 0x002F4E2C: sysObserve(uid): `observer` will receive this script's sysNotify() events.
void AMXLoader::registerObserver(AMXLoader *observer)
{
	int bit = observer->index;
	lastObserver = bit;
	if (!(observers[bit >> 3] & (1 << (bit & 7)))) {
		observers[bit >> 3] |= 1 << (bit & 7);
		observerCount++;
	}
}

// 0x002538F8
bool AMXLoader::isFinished()
{
	return finished;
}

// ---- ScriptAMXLoader ------------------------------------------------------------------------

// 0x00242FFC
ScriptAMXLoader::ScriptAMXLoader()
{
	// AMXLoader part (constructor inlined)
	path[0] = '\0';
	name[0] = '\0';
	memset(observers, 0, sizeof(observers));
	lastObserver = 0;
	observerCount = 0;
	enabled = 1;
	index = s_count;
	if (!s_main) {
		s_main = this;
	}
	s_count++;
}

// 0x001823DC: loads romfs:/amx/<name>.amx and starts it on the next run() (from main()).
int ScriptAMXLoader::load(const char *name, int stackSize)
{
	char work[0x180];
	strncpy(work, "amx", sizeof(work));   // leftover: memory profiler label
	System::getMainMemAllocator();        // result unused (stripped debug code)

	for (int i = 0; i < 300; i++) {
		publicCache[i] = -1;
	}

	char path[0x80] = "";
	strncat(path, "amx/", sizeof(path));
	strncat(path, name, sizeof(path));
	strncat(path, ".amx", sizeof(path));
	AMX_HEADER *file = (AMX_HEADER *)Resource::getFile(path, 0, 0x80);

	// The memory block holds the whole image plus the requested stack (hdr->stp is the end of the
	// data + heap + stack area); blocks are recycled between modes (MemBlock::findStock).
	file->stp += stackSize;
	amx_Align32((u32 *)&file->stp);    // byte-order helpers of amx.c: no-ops on this CPU
	amx_Align32((u32 *)&file->size);
	memory = MemBlock::findStock(file->stp, 4);
	if (!memory) {
		memory = new MemBlock(file->stp, 4);
	}
	memory->attach();
	u8 *image = *(u8 **)memory;          // first field of MemBlock: the buffer
	memset(image, 0, file->stp);
	memcpy(image, file, file->size);

	memset(&amx, 0, sizeof(amx));
	amx_Init(&amx, image);
	freezeState(&frozen);
	depth = 0;

	amx_ConsoleInit(&amx);
	amx_CoreInit(&amx);
	amx_SystemInit(&amx);
	amx_StringInit(&amx);
	amx_GfxInit(&amx);
	amx_VectorInit(&amx);
	amx_FloatInit(&amx);
	amx_EffectsInit(&amx);
	amx_XMLInit(&amx);
	amx_OnlineInit(&amx);
	amx_SoundInit(&amx);
	amx_BBInit(&amx);
	amx_DynamicsInit(&amx);
	amx_WorldInit(&amx);
	amx_ActorInit(&amx);

	eventMessage = findPublic("@eventMessage");
	starting = true;
	strncpy(this->path, path, sizeof(this->path));
	strncpy(this->name, name ? name : "", sizeof(this->name));
	System::getMainMemAllocator();
	return 0;
}

// 0x00182754
void ScriptAMXLoader::cleanup()
{
	if (memory) {
		memory->release();
		memory = NULL;
	}
	AMXLoader::cleanup();   // inlined
}

// 0x0024A178: one frame of the script.
void ScriptAMXLoader::run()
{
	s_current.SetValue(this);
	preExecute();
	if (!finished) {
		thawState(&frozen);
		cell retval = 0x7A31C7;   // sentinel, never read
		depth++;
		int error = amx_Exec(&amx, &retval, starting ? AMX_EXEC_MAIN : AMX_EXEC_CONT);
		depth--;
		if (error == AMX_ERR_EXIT) {
			finished = true;
		} else if (error != 0 && error != AMX_ERR_SLEEP) {
			// The retail build patched out a log of the error: its arguments (the error code,
			// a table of 32-byte error strings indexed by it, the script's path) are still set up.
		}
		freezeState(&frozen);
		starting = false;
		finished = finished || error != AMX_ERR_SLEEP;
	}
	s_executing--;
}

// 0x001820B0
int ScriptAMXLoader::findPublic(const char *name)
{
	// Global id of the name, added to the table on first use.
	u32 bucket = hashName(name);
	PublicName *entry = s_publicNames[bucket];
	while (entry && strcmp(entry->name, name) != 0) {
		entry = entry->next;
	}
	if (!entry) {
		Heap previous = System::useHeap(System::getSysHeap());
		entry = new PublicName();
		strncpy(entry->name, name ? name : "", sizeof(entry->name));
		entry->id = s_publicNameCount++;
		entry->prev = NULL;
		entry->next = s_publicNames[bucket];
		if (entry->next) {
			entry->next->prev = entry;
		}
		s_publicNames[bucket] = entry;
		System::useHeap(previous);
	}

	// Index in this script, cached per id.
	int index = publicCache[entry->id];
	if (index == -1) {
		if (amx_FindPublic(&amx, name, &index) != AMX_ERR_NONE) {
			index = -1;
		}
		publicCache[entry->id] = index;
	}
	return index;
}

// 0x00182274
void ScriptAMXLoader::freezeState(AMXState *state)
{
	state->frm = amx.frm;
	state->stk = amx.stk;
	state->hea = amx.hea;
	state->pri = amx.pri;
	state->alt = amx.alt;
	state->cip = amx.cip;
	state->reset_stk = amx.reset_stk;
	state->reset_hea = amx.reset_hea;
}

// 0x001828C0
void ScriptAMXLoader::thawState(const AMXState *state)
{
	amx.frm = state->frm;
	amx.stk = state->stk;
	amx.hea = state->hea;
	amx.pri = state->pri;
	amx.alt = state->alt;
	amx.cip = state->cip;
	amx.reset_stk = state->reset_stk;
	amx.reset_hea = state->reset_hea;
}

// 0x001822B8: calls a public function from C++ (the arguments were pushed before).
cell ScriptAMXLoader::callFunction(int index)
{
	AMXLoader *caller = (AMXLoader *)s_current.GetValue();
	s_current.SetValue(this);
	cell retval = 0x7A31C7;
	depth++;
	int error = amx_Exec(&amx, &retval, index);
	depth--;
	if (error == AMX_ERR_EXIT) {
		finished = true;
	}
	s_current.SetValue(caller);
	return retval;
}

// 0x00319E3C (amx_Push inlined, with a 0x40-byte safety margin above the heap)
int ScriptAMXLoader::pushArg(cell value)
{
	if (amx.stk < amx.hea + 0x40) {
		return AMX_ERR_STACKERR;
	}
	u8 *data = amx.data ? amx.data : amx.base + ((AMX_HEADER *)amx.base)->dat;
	amx.stk -= sizeof(cell);
	amx.paramcount++;
	*(cell *)(data + amx.stk) = value;
	return AMX_ERR_NONE;
}

// 0x00182388
int ScriptAMXLoader::pushArgArray(cell *array, int count)
{
	return amx_PushArray(&amx, NULL, NULL, array, count);
}

// 0x001823AC
void ScriptAMXLoader::pushArgString(const char *string)
{
	amx_PushString(&amx, NULL, NULL, string, false, false);
}

// 0x001827CC
cell *ScriptAMXLoader::getAddr(cell amx_addr, int index)
{
	cell *address;
	amx_GetAddr(&amx, amx_addr, &address);
	return address + index;
}

// 0x001827F0: unpacked strings only (one character per cell), at most 0x180 characters.
void ScriptAMXLoader::getString(char *dest, cell amx_addr)
{
	cell *source = getAddr(amx_addr, 0);
	for (u16 i = 0; i < 0x180; i++) {
		dest[i] = (char)source[i];
		if (dest[i] == '\0') {
			return;
		}
	}
}

// 0x0018283C: writes an unpacked string; no size check.
void ScriptAMXLoader::setString(const char *src, cell amx_addr)
{
	cell *dest = getAddr(amx_addr, 0);
	u32 length = strlen(src);
	for (u32 i = 0; i < length; i++) {
		dest[i] = (u8)src[i];
	}
	dest[length] = 0;
}

// 0x003102CC: static initialiser of amxloader.o.
static void __sti___13_amxloader_cpp()
{
	s_unknown68 = -1;   // 0x0038DD68..0x0038DD74, meaning unknown
	s_unknown6C = -1;
	s_unknown70 = 0;
	s_unknown74 = 0;
	new (&s_current) nn::os::ThreadLocalStorage();
	new (&s_threads) nn::os::Thread[10];
	memset(s_publicNames, 0, sizeof(s_publicNames));
}
