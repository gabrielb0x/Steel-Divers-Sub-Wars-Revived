// source/amx/amxsys.cpp (amxsys.o): the system natives of the scripts (table natives_System, registered by
// amx_SystemInit 0x00171A14): the script globals, the save, the shop, the inputs, time, calls and messages
// between scripts, texts, the profanity filter, and the console's settings.
//
// Reconstructed by hand from decomp/raw/source/amx/amxsys.cpp and the disassembly. Not compilable on its
// own. Many natives of 4 or 8 bytes run into the function after them (their body is that function).

// ---- script globals: sysSetGlobal / sysGetGlobal, sysSetGlobalArray / sysGetGlobalArray ----
// Every script shares them: "mode.current", "player.sub", "save.sub.unlock"... Two hash tables of 4096
// buckets, of nodes of 0x4C bytes: name (0x40 bytes), value (an integer, or {count, cells} for an array),
// previous and next node of the bucket. The hash is h = h * 33 + c over the first 64 characters, & 0xFFF.
struct Global {
	char name[0x40];                     // +0x00
	union { cell value; GlobalArray *array; };   // +0x40 (an array: {int count; cell *cells})
	Global *prev, *next;                 // +0x44, +0x48
};
static Global *s_integers[0x1000];       // 0x003B9054
static Global *s_arrays[0x1000];         // 0x003BD054

static u32 hashName(const char *name)
{
	char key[0x40];
	strncpy(key, name, sizeof(key));
	u32 h = 0;
	for (const char *c = key; *c; c++) {
		h = h * 33 + (u8)*c;
	}
	return h & 0xFFF;
}

// 0x00328D38: sysGetGlobal(name): 0 when the global does not exist.
// 0x00328DFC: sysGetGlobalArray(name, dest[], count, offset): copies count cells, returns false (and leaves
// dest alone) when the array does not exist.
// 0x001DA344 amxSysSetGlobalArray(name, cells, count) / 0x002539C4 amxSysSetGlobal(name, value): create the
// node in the system heap if needed, then copy. The natives sysSetGlobal(Array) (0x0032A6D0, 0x0032A714)
// only read the script's string and array and call them, without locking anything: the scripts and the
// engine use them from the main thread, and the save thread takes amxSysGetMutex(0).

// ---- the save (format: docs/formats.md#save) ----

// 0x00329FD8: sysSaveDataSave(prefix, version). The scripts call sysSaveDataSave("save", 27) (save.inc,
// @saveAll): every global whose name starts with the prefix is written. Built in a 0x22000-byte memory
// stream (0x0038DDB0, allocated once in the system heap), then handed to the save thread.
cell n_sysSaveDataSave(AMX *amx, cell *params)
{
	char prefix[0x180];
	AMXLoader::getCurrentLoader()->getString(prefix, params[1]);
	u32 version = params[2];

	// First pass: count the globals with the prefix and the size they need.
	int integers = 0, arrays = 0;
	u32 size = 12;
	for (Global *g : all(s_integers)) {
		if (startsWith(g->name, prefix)) {
			integers++;
			size += strlen(g->name) + 5;                      // name, NUL, value
		}
	}
	for (Global *g : all(s_arrays)) {
		if (startsWith(g->name, prefix)) {
			arrays++;
			size += strlen(g->name) + 5 + g->array->count * 4;    // name, NUL, count, cells
		}
	}

	MemStream *out = s_saveStream;                            // created on first use
	out->size = size;
	out->position = 0;
	out->write(&version, 4);
	out->write(&integers, 4);
	out->write(&arrays, 4);
	for (Global *g : all(s_integers)) {
		if (startsWith(g->name, prefix)) {
			out->write(g->name, strlen(g->name) + 1);
			out->write(&g->value, 4);
		}
	}
	for (Global *g : all(s_arrays)) {
		if (startsWith(g->name, prefix)) {
			out->write(g->name, strlen(g->name) + 1);
			out->write(&g->array->count, 4);
			out->write(g->array->cells, g->array->count * 4);
		}
	}
	SaveData::writeandclose(prefix, out->data, out->getSize());   // the file is named after the prefix
	return true;
}

// 0x00329C08: sysSaveDataLoad(name, version): false when there is no save, when it is damaged (CRC) or of
// another version; otherwise every value becomes a global again.
cell n_sysSaveDataLoad(AMX *amx, cell *params)
{
	char name[0x18C];
	AMXLoader::getCurrentLoader()->getString(name, params[1]);
	u8 *data;
	u32 size;
	if (!SaveData::read(name, &data, &size)) {
		return false;
	}
	MemStream in(data, size);
	u32 version, integers, arrays;
	in.read(&version, 4);
	if (version != (u32)params[2]) {
		return false;
	}
	in.read(&integers, 4);
	in.read(&arrays, 4);
	for (u32 i = 0; i < integers; i++) {
		char key[0x400];
		in.readString(key, sizeof(key));                      // byte by byte up to the NUL
		cell value;
		in.read(&value, 4);
		amxSysSetGlobal(key, value);
	}
	for (u32 i = 0; i < arrays; i++) {
		char key[0x400];
		in.readString(key, sizeof(key));
		u32 count;
		in.read(&count, 4);
		cell cells[0x400];
		in.read(cells, count * 4);
		amxSysSetGlobalArray(key, cells, count);
	}
	return true;
}

// 0x00329914 sysSaveDataClear(name): SaveData::rm. 0x00329C00 sysSaveDataFormat: SaveData::format(true).
// 0x002F3494 sysSaveDataBusy: SaveData::busy(). 0x0032A590 sysSaveDebugFormat(on): SaveData::setDebugFormat.

// ---- the shop (decomp/src/sys/dlc.cpp) ----
// 0x0013A054 sysDLCCheckCondition(n) and 0x002F1EE4 sysDLCCheckPaidForFullVer() are a push, a call to
// getNsubShop() and a pop, then they run into NsubShop::checkCondition / checkPaidForFullVer, placed right
// after them by the compiler: patching those two (mods/premium) changes the natives too.
cell n_sysDLCCheckPaidForFullVer(AMX *amx, cell *params) { return getNsubShop()->checkPaidForFullVer(); }
cell n_sysDLCCheckCondition(AMX *amx, cell *params) { return getNsubShop()->checkCondition(params[1]); }
// 0x00328488 sysDLCUpdateCondition: getNsubShop()->updateCondition(), returns 0.
// The others (sysDLCPurchaseItem 0x002F15D4, sysDLCRedownloadItem 0x002F172C, sysDLCValidateSession
// 0x002F1934, sysDLCAc* 0x00182E34..0x003280E0, sysDLCGetItem*...) call the NsubShop / NsubAcConnection
// method of the same name, or read NsubShop::items[item].

// ---- module state --------------------------------------------------------------------------------------
static char *s_filterBuffer;            // 0x0038DDA8 16 KB: the string to filter, in UTF-16
static nn::ngc::ProfanityFilter *s_filter;   // 0x0038DDAC
static u32 s_observer;                  // 0x0038DDB4 the script receiving the system's events (sysObserveSystem)
static nn::os::Thread s_filterThread;   // 0x0038DDB8
static char s_modeScript[384];          // 0x003B8EC4 the mode to start next (sysSetModeScript)
static nn::os::Mutex *s_mutexes[4];     // 0x003B9044 amxSysGetMutex: 0 scripts and world, 1 the filter,
                                        // 3 the Miis (facesystem.cpp)

// 0x00101118: the profanity filter, its buffer, the four mutexes.
void amxSysInit()
{
	s_filter = new nn::ngc::ProfanityFilter();
	s_filter->Initialize();
	s_filterBuffer = (char *)alloc(0x4000);
	for (auto &m : s_mutexes) {
		m = new nn::os::Mutex();
		m->Initialize();
	}
}

void amxSysReset() { s_observer = 0; }                                  // 0x001011D0
u32 amxSysObserverUID() { return s_observer; }                          // 0x0011066C
nn::os::Mutex *amxSysGetMutex(int i) { return s_mutexes[i]; }           // 0x00253974
const char *amxGetModeScript() { return s_modeScript; }                 // 0x00253B28 (main.cpp)
void amxSetModeScript(const char *name) { strncpy(s_modeScript, name ? name : "", 384); }   // 0x00101308

// ---- the system's events, to the observer script ---------------------------------------------------------

// 0x0024999C: a public of the observing script, with arguments.
static cell callEvent(const char *name, const cell *args, u32 count)
{
	AMXLoader *observer = s_observer ? AMXLoader::uidToAmx(s_observer) : nullptr;
	int index;
	if (observer == nullptr || (index = observer->findPublic(name)) < 0)
		return 0;
	AMXState state;
	observer->freezeState(&state);
	for (u32 i = count; i-- > 0;)
		observer->pushArg(args[i]);
	observer->callFunction(index);
	observer->thawState(&state);
	return 0;
}

// Load errors are calls; the save's are globals the mode script polls ("mode.save*").
void amxEventConnectionLost() { callEvent("@eventConnectionLost", nullptr, 0); }              // 0x00107960
void amxEventLoadOpenFail(cell e) { callEvent("@eventLoadOpenFail", &e, 1); }                  // 0x00174288
void amxEventLoadReadFail(cell e) { callEvent("@eventLoadReadFail", &e, 1); }                  // 0x001DF540
void amxEventLoadCorruptData() { callEvent("@eventLoadCorruptData", nullptr, 0); }            // 0x00174B38
void amxEventSaveOpenFail(cell e) { amxSysSetGlobal("mode.saveopenfail", e); }                 // 0x001742B4
void amxEventSaveWriteFail(cell e) { amxSysSetGlobal("mode.savewritefail", e); }               // 0x00218FA0
void amxEventSaveWriteSuccess() { amxSysSetGlobal("mode.savewritesuccess", 1); }               // 0x00174BA0
void amxEventLoadSaveMountFail(cell e) { amxSysSetGlobal("mode.savemountfail", e); }           // 0x00174BD0
void amxEventLoadSaveUnmountFail(cell e) { amxSysSetGlobal("mode.saveunmountfail", e); }       // 0x00174DE0
void amxEventLoadSaveFormatFail(cell e) { amxSysSetGlobal("mode.saveformatfail", e); }         // 0x00219040

// ---- scripts: identity, observers, calls, messages -----------------------------------------------------

static cell n_sysGetUID(AMX *, const cell *) { return AMXLoader::getCurrentLoader()->uid; }                    // 0x001DB150
static cell n_sysSetUID(AMX *, const cell *p) { AMXLoader::getCurrentLoader()->uid = p[1]; return 0; }         // 0x0032A870
static cell n_sysObserveSystem(AMX *, const cell *) { s_observer = AMXLoader::getCurrentLoader()->uid; return 0; }   // 0x003297C8
static cell n_sysUnobserveSystem(AMX *, const cell *) { s_observer = 0; return 0; }                           // 0x0032A920

// 0x00329798: sysObserve(uid): the calling script observes uid (0: itself); 0x0032973C sysNotify(event[],
// ...): the observers of the calling script get the event (AMXLoader::notifyObservers, amxloader.cpp).
static cell n_sysObserve(AMX *, const cell *p)
{
	AMXLoader *observer = AMXLoader::getCurrentLoader();
	(p[1] ? AMXLoader::uidToAmx(p[1]) : observer)->registerObserver(observer);
	return 0;
}

static cell n_sysNotify(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char event[384];
	self->getString(event, p[1]);
	self->notifyObservers(event, p + 2, p[0] / sizeof(cell) - 1);
	return 0;
}

// 0x00327CC4: sysCallPublic(uid, function[], ...): at once, in the other script (0: this one), the values
// of the arguments (they are references).
static cell n_sysCallPublic(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char function[384];
	self->getString(function, p[2]);
	AMXLoader *target = p[1] ? AMXLoader::uidToAmx(p[1]) : self;
	int index;
	if (target == nullptr || (index = target->findPublic(function)) < 0)
		return 0;
	AMXState state;
	target->freezeState(&state);
	for (u32 i = p[0] / sizeof(cell); i > 2; i--)
		target->pushArg(*self->getAddr(p[i], 0));
	target->callFunction(index);
	target->thawState(&state);
	return 0;
}

// 0x00327F24: sysCallPublicf(uid, function[], format[], ...): 's' arguments are passed as strings.
static cell n_sysCallPublicf(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	AMXLoader *target = p[1] ? AMXLoader::uidToAmx(p[1]) : self;
	char function[384], format[384], string[384];
	self->getString(function, p[2]);
	self->getString(format, p[3]);
	int index;
	if (target == nullptr || (index = target->findPublic(function)) < 0)
		return 0;
	AMXState state;
	target->freezeState(&state);
	for (int i = p[0] / sizeof(cell) - 4; i >= 0; i--) {
		if (format[i] == 's') {
			self->getString(string, p[4 + i]);
			target->pushArgString(string);
		} else {
			target->pushArg(*self->getAddr(p[4 + i], 0));
		}
	}
	target->callFunction(index);
	target->thawState(&state);
	return 0;
}

// 0x00327E04: sysCallPublicDelayed(uid, frames, function[], ...): one of the target's 16 delayed calls
// (AMXLoader::delayed, run by its frame loop). False when none is free or the function is missing.
static cell n_sysCallPublicDelayed(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	AMXLoader *target = p[1] ? AMXLoader::uidToAmx(p[1]) : self;
	char function[384];
	self->getString(function, p[3]);
	int index;
	if (target == nullptr || (index = target->findPublic(function)) < 0)
		return 0;
	u32 count = p[0] / sizeof(cell) - 3;
	for (auto &d : target->delayed) {
		if (d.frames == 0) {
			d.function = index;
			d.frames = p[2];
			d.argCount = count;
			for (u32 i = 0; i < count; i++)
				d.args[i] = *self->getAddr(p[4 + i], 0);
			return 1;
		}
	}
	return 0;
}

// 0x0032A5AC: sysSendMessage(uid, message, value, flags): into the target's queue of 8 (its @eventMessage
// gets it next frame), with the sender's UID and the flags in the high half of the target. Only flags 0,
// or with bit 0 set, are delivered; any other is dropped.
static cell n_sysSendMessage(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	u32 flags = p[4];
	if ((flags & 1) || (flags & 0xFFFF) == 0) {
		if (AMXLoader *target = AMXLoader::uidToAmx(p[1]))
			target->queueMessage(self->uid, p[1] | flags << 16, p[2], p[3]);
	}
	return 1;
}

// 0x00329808: sysQueueMessage(from, message, value): into the calling script's own queue.
static cell n_sysQueueMessage(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	self->queueMessage(p[1], p[1], p[2], p[3]);
	return 0;
}

// 0x0032966C: sysLoadScript(name[]): a new script (ScriptAMXLoader, 0xCF8 bytes), loaded and running; its
// address is returned. sysRunScript (0x0032990C) does nothing.
static cell n_sysLoadScript(AMX *, const cell *p)
{
	char name[384];
	AMXLoader::getCurrentLoader()->getString(name, p[1]);
	ScriptAMXLoader *script = new ScriptAMXLoader();
	script->init();
	script->load(name, 0);
	return (cell)script;
}

static cell n_sysSetModeScript(AMX *, const cell *p) { AMXLoader::getCurrentLoader()->getString(s_modeScript, p[1]); return 0; }   // 0x0032A808

// ---- inputs (controller.cpp; `set`: 0 the console, 1 the debug pad as 3DS buttons, 2 the debug pad) ------

static cell n_sysGetButtonsClicked(AMX *, const cell *p) { return System::getController()->sets[p[1] & 0xFF].clicked; }    // 0x003288B8
static cell n_sysGetButtonsDown(AMX *, const cell *p) { return System::getController()->sets[p[1] & 0xFF].down; }          // 0x003288D8
static cell n_sysGetButtonsReleased(AMX *, const cell *p) { return System::getController()->sets[p[1] & 0xFF].released; }  // 0x003288FC
static cell n_sysGetButtonsRepeated(AMX *, const cell *p) { return System::getController()->sets[p[1] & 0xFF].repeated; }  // 0x00328920
// 0x0032A678 / 0x0032A69C: buttons pressed by a script (the tutorial, the demo): or-ed into set 0.
static cell n_sysSetButtonsClicked(AMX *, const cell *p) { System::getController()->sets[0].clicked |= p[1]; return 0; }
static cell n_sysSetButtonsDown(AMX *, const cell *p) { System::getController()->sets[0].down |= p[1]; return 0; }

static cell n_sysGetStick(AMX *, const cell *p)              // 0x00329140: [x, y], -145..145
{
	cell *out = AMXLoader::getCurrentLoader()->getAddr(p[1], 0);
	out[0] = System::getController()->stickX;
	out[1] = System::getController()->stickY;
	return 0;
}

static cell n_sysGetExtraStick(AMX *, const cell *p)         // 0x00328C5C: the right stick
{
	cell *out = AMXLoader::getCurrentLoader()->getAddr(p[1], 0);
	out[0] = System::getController()->extraStickX;
	out[1] = System::getController()->extraStickY;
	return 0;
}

static cell n_sysGetTouchPad(AMX *, const cell *p)           // 0x00329424: [x, y], true while touched
{
	Controller *c = System::getController();
	cell *out = AMXLoader::getCurrentLoader()->getAddr(p[1], 0);
	out[0] = c->touchX;
	out[1] = c->touchY;
	return c->touching;
}

// 0x00328858 / 0x00328F60: the acceleration (g) and the gyroscope's angles (radians), 3 floats each;
// 0x00328FB8 / 0x00328FCC: Float bearing and elevation.
static cell n_sysGetAcceleration(AMX *, const cell *p) { VEC3 v; System::getController()->getAcceleration(&v); memcpy(AMXLoader::getCurrentLoader()->getAddr(p[1], 0), &v, 12); return 0; }
static cell n_sysGetGyroAngle(AMX *, const cell *p) { VEC3 v; System::getController()->getGyroAngle(&v); memcpy(AMXLoader::getCurrentLoader()->getAddr(p[1], 0), &v, 12); return 0; }
static cell n_sysGetGyroBearing(AMX *, const cell *) { return amx_ftoc(System::getController()->getGyroBearing()); }
static cell n_sysGetGyroElevation(AMX *, const cell *) { return amx_ftoc(System::getController()->getGyroElevation()); }

// The Circle Pad Pro: 0x00328828 / 0x0032883C sampling on and off, 0x00176324 / 0x00176368 its battery and
// connection (their array argument is read and unused).
static cell n_sysExtraPadStartSampling(AMX *, const cell *) { Controller::enableExtraPad(); return 0; }
static cell n_sysExtraPadStopSampling(AMX *, const cell *) { Controller::disableExtraPad(); return 0; }
static cell n_sysCheckExtraPadBattery(AMX *, const cell *) { return Controller::checkExtraPadBattery(); }
static cell n_sysCheckExtraPadConnected(AMX *, const cell *) { return Controller::checkExtraPadConnected(); }

// ---- time ----------------------------------------------------------------------------------------------

static cell n_sysGetFrameNum(AMX *, const cell *) { return System::s_frame; }                   // 0x0010D1D8
static cell n_sysGetVFrameNum(AMX *, const cell *) { return Graphics::s_vblankCount; }          // 0x003294F4
static cell n_sysReadSystemTime(AMX *, const cell *) { return amx_ftoc(System::getRunningTimeInSeconds()); }   // 0x003298B0
// 0x002ED0C0.. (thunks): the console's clock, nn::fnd::DateTime::GetNow: sysGetYear, sysGetMonth, sysGetDay,
// sysGetHour, sysGetMinute; 0x00329118 sysGetRandomSeed: the current time as a number.
// 0x00253FF8 sysNewTimer: 1, then it runs into operator new: it returns a new 1-byte block (never freed)
// as a handle; sysStartTimer, sysStopTimer, sysReadTimer, sysResetTimer, sysGetFrameTime return 0.
// 0x001DD0F0 system_rndseed: System::random(0x7FFFFFFF).

// ---- texts ---------------------------------------------------------------------------------------------

// 0x0032922C: sysGetString(dest[], key[]): the text of a key (the key itself if missing).
static cell n_sysGetString(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char key[384];
	self->getString(key, p[2]);
	TextStyle t = TextData::find(key, true);
	self->setString(t.text ? t.text : key, p[1]);
	return 0;
}

// 0x00328C9C: sysGetFormattedString(dest[], unused, key[], ...): the text with its "#N" placeholders
// replaced by the string arguments (keystring_sprintf, amxutils.cpp).
static cell n_sysGetFormattedString(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char key[384];
	self->getString(key, p[3]);
	char *out = getAmxScratchBuffer1();
	keystring_sprintf(out, 0x400, TextData::find(key, true).text, p, 4, self);
	self->setString(out, p[1]);
	return 0;
}

// 0x003292BC: the number of line feeds of a text.
static cell n_sysGetStringLineFeedNum(AMX *, const cell *p)
{
	char key[384];
	AMXLoader::getCurrentLoader()->getString(key, p[1]);
	const char *text = TextData::find(key, true).text;
	int n = 0;
	for (const char *c = text ? text : ""; *c; c++)
		n += *c == '\n';
	return n;
}

// 0x003290DC / 0x00329338: characters of a UTF-8 string; sysGetSubstringUTF8(dest[], source[], first, end).
// (An empty range writes "" into source, not dest.)
static cell n_sysGetNumGlyphsUTF8(AMX *, const cell *p) { char s[384]; AMXLoader::getCurrentLoader()->getString(s, p[1]); return UTF8_Length(s); }
static cell n_sysGetSubstringUTF8(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char s[384];
	self->getString(s, p[2]);
	char *end = s + strlen(s);
	int first = p[3], last = p[4];
	if (first == last) {
		self->setString("", p[2]);
		return 0;
	}
	char *from = s, *to = s;
	for (int i = 0; i < first; i++)
		from = to = nextGlyphUTF8(from, end);
	for (int i = first; i < last; i++)
		to = nextGlyphUTF8(to, end);
	*to = 0;
	self->setString(from, p[1]);
	return 0;
}

// 0x00329550: sysKanaConvertString(dest[], source[], size): romaji to kana (IME::to_kana, ime.cpp).
static cell n_sysKanaConvertString(AMX *, const cell *p);

// 0x003296F0: sysLoadStrings(language[]) and the default font of its "DEFAULT" style; 0x003295F0
// sysLoadFonts(list[]) into the device memory's permanent group ("prm": group 0, then 1 again).
static cell n_sysLoadStrings(AMX *, const cell *p)
{
	char language[384];
	AMXLoader::getCurrentLoader()->getString(language, p[1]);
	TextData::loadStrings(language);
	Font::setDefaultFont(TextData::getDefaultStyle()->typeface);
	return 0;
}

// 0x00328FE0: sysGetLanguage(dest[]): "<language>_<region>" (System::getLanguage / getRegion).
// 0x00329040: sysGetNickname(dest[]): the console's user name (nn::cfg), in UTF-8.
// 0x003294F8: sysGetVersion(dest[]): System::getVersionText().
// 0x0021BB30: sysGetVersionChecksum(): the CRC-32 of the build's revision text (System::s_revision,
// "31308" in v0): the version the online search compares (docs/online.md).
// 0x0032A8B0: sysShowKeyboard(dest[], kind, ...): the software keyboard applet (96 bytes), true if confirmed.

// ---- the profanity filter (nn::ngc) ------------------------------------------------------------------

// 0x003285CC: sysDoGetStringFilteredThread(text[], unused, kind, value): checks a text in a thread; the
// answer comes back as a call. Kind 0: a Morse chat message, to UID_MESSAGE_QUEUE's
// @morseProcessFilteredString(ok, value, extra); kinds 1 to 3: the player's name, to the mode's
// @applyFilteredPlayerName(ok, 1 for kind 1 else 0, the player's Mii[]).
// A text with 6 digits or more is refused (a phone number, a friend code: the system's rule); otherwise
// kind 0 is refused when it contains a word of the console's list, kinds 1 and 2 when the filter masks
// something; kind 3 is always accepted.
static void sysFilterString(int kind, cell value, int extra);           // 0x00172254, thread 0x00174C74

// ---- the console ---------------------------------------------------------------------------------------

// 0x002EC958: sysGetContinent(): the console's country (nn::cfg's code) as the region of the online search
// (network.continent, attribute 0; docs/online.md). Codes per region:
//   1 Japan: 1
//   5 North and Central America, the Caribbean, Argentina: 8..14, 17..19, 22..24, 26, 28..30, 32..40, 43..45,
//     47..49, 51
//   7 South America: 15, 16, 20, 21, 25, 27, 31, 41, 42, 46, 50, 52
//   4 Europe: 64, 66..68, 70, 71, 73..84, 86..91, 94, 96..103, 105, 107, 108, 110, 122..127, 184, 185
//   6 Australia and New Zealand: 65, 95
//   2: 69, 85, 92, 93, 104, 106, 111, 112, 114..121, 170
//   3: 72, 109, 113, 128, 136, 144, 145, 152..156, 160, 168, 169, 171..177
//   0: any other
// 0x002ED170: sysIsFriend(principalId): one of the console's 100 friends (nn::friends).
// 0x0032946C: sysGetTransferableId(): a number from the console: the current date's fields (year, then
// month, day, hour, minute, second, each > 0) multiplied together, times nn::cfg's transferable id.
// 0x0032880C: sysEulaConfirm(): the console agreed to the online services' terms, else the system's
// screen asks (System::showEULAConfirm).
// The rest are one call or one value: sysEnableHomeButton / sysEnableSleep (System), sysIsHomeButtonEnabled
// / sysIsSleepEnabled / sysIsPaused (System's flags), sysIsCoppaSupported / sysGetCoppaRestriction /
// sysAuthCoppaPIN / sysIsCoppaPINAuth / sysJumpToParentalControlCoppa (the US parental control, COPPA),
// sysIsRestrictPhotoExchange (parental control), sysIsMiiDataFormatted (FaceSystem), sysGetStoreDataName
// (FaceSystem::getStoreDataName), sysSaveIsEnabled (1), sysGetBuildType (0), sysJumpToSystemMenu,
// sysDebug, sysDumpLog, sysDumpProfile, sysEnableLogging, sysPrintStats, sysGetAMXProfiles,
// sysGetLayoutProfiles, sysGetTimerProfiles (0: emptied), sysDumpModels (Renderer::dumpModels of the four
// renderers), sysPrintResourceList, sysBeginProfilePoint / sysEndProfilePoint (amxutils.cpp).
// 0x00328948: sysGetDirectoryListing(path[], &bxml, stripExtension): the files of "rom:/<path>" as a new
// BXML document (<path><model name="..."/>...</path>), its address returned in the cell — a debug helper.
