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
// 0x002F1934, sysDLCAcConnect 0x00182E34...) call the NsubShop / NsubAcConnection method of the same name:
static cell n_sysDLCInit(AMX *, const cell *) { getNsubShop()->initializeEc(); return 0; }                        // 0x00328330
static cell n_sysDLCCreateCatalog(AMX *, const cell *) { getNsubShop()->createCatalog(); return 0; }              // 0x003280F4
static cell n_sysDLCDestroyCatalog(AMX *, const cell *) { getNsubShop()->destroyCatalog(); return 0; }            // 0x00328124
static cell n_sysDLCFinalizeMetaDataReader(AMX *, const cell *) { getNsubShop()->finalizeMetaDataReader(); return 0; }   // 0x00328138
static cell n_sysDLCGetBalanceAsync(AMX *, const cell *) { getNsubShop()->getBalanceAsync(); return 0; }          // 0x0032814C
static cell n_sysDLCGetContentSetListAsync(AMX *, const cell *) { getNsubShop()->getContentSetListAsync(); return 0; }   // 0x003281EC
static cell n_sysDLCGetServerTimeAsync(AMX *, const cell *) { getNsubShop()->getServerTimeAsync(); return 0; }    // 0x0032831C
static cell n_sysDLCDeleteItemAsync(AMX *, const cell *p) { getNsubShop()->deleteItemAsync(p[1]); return 0; }     // 0x00328108
static cell n_sysDLCInvalidateSession(AMX *, const cell *) { getNsubShop()->invalidateSession(); return 0; }       // 0x00328344
static cell n_sysDLCAcDisconnect(AMX *, const cell *) { getNsubAcConnection()->disconnect(); return 0; }          // 0x003280CC
// 0x00182F28: getNsubAcConnection(), then it runs into NsubAcConnection::isConnected (dlc.cpp).
static cell n_sysDLCAcIsConnected(AMX *, const cell *) { return getNsubAcConnection()->isConnected(); }
static cell n_sysDLCSetFilterModeEnlist(AMX *, const cell *) { getNsubShop()->filterMode = 1; return 0; }         // 0x00328454
static cell n_sysDLCSetFilterModeSubmarine(AMX *, const cell *) { getNsubShop()->filterMode = 0; return 0; }      // 0x00328470

// 0x002F0AE8: the eShop's "add funds" applet (EcApplet::RequestManageBalance); false if it failed.
static cell n_sysDLCAddBalance(AMX *, const cell *)
{
	Result r = getNsubShop()->applet.RequestManageBalance();
	return r.IsSuccess() ? 1 : ReportEcErrorVerbose(r);
}

// 0x002F1F94: the metadata reader of the catalog; false (and the error dialog) if it failed.
static cell n_sysDLCInitializeMetaDataReader(AMX *, const cell *)
{
	NsubShop *shop = getNsubShop();
	Result r = shop->metaData.Initialize(shop->dataTitle);
	if (r.IsFailure())
		ReportEcErrorVerbose(r);
	return r.IsSuccess();
}

// 0x002F17DC: the last request's result; a failure shows its error dialogs.
static cell n_sysDLCCheckLastResult(AMX *, const cell *)
{
	NsubShop *shop = getNsubShop();
	if (shop->lastResult.IsFailure()) {
		ReportNnError(shop->lastResult);
		ReportEcErrorVerbose(shop->lastResult);
	}
	return shop->lastResult.IsSuccess();
}

// 0x003283C4: the player closed the eShop applet (result 0xC9213801); 0x003283EC: the request failed with
// one of 0xC8A13817..0xC8A13819 (the eShop's own refusals, which the scripts explain themselves).
static cell n_sysDLCIsLastAppletCancelled(AMX *, const cell *) { return getNsubShop()->lastResult == 0xC9213801; }
static cell n_sysDLCIsLastResultFailed(AMX *, const cell *)
{
	u32 r = getNsubShop()->lastResult;
	return r == 0xC8A13817 || r == 0xC8A13818 || r == 0xC8A13819;
}

// 0x0032849C: has the request's thread ended (a wait of 0)? Then it is joined and closed: 1; still running: 0.
static cell n_sysDLCWaitThread(AMX *, const cell *)
{
	NsubShop *shop = getNsubShop();
	if (shop->thread.IsValid() && !shop->thread.TryWait())
		return 0;
	if (shop->thread.IsValid()) {
		shop->thread.Join();
		shop->thread.Finalize();
	}
	return 1;
}

// The catalog's items (NsubShop::items[item], 0x300 bytes, filled by _setItemInfo): name +0x24, long
// description +0x1A4, price text +0x2A4, release time +0x2E8 (u64, milliseconds), purchased +0x2F2, on the
// SD card +0x2F3, purchasable +0x2F5, new +0x2F6, blocks needed +0x2F8.
static cell itemString(const cell *p, int offset)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char *out = getAmxScratchBuffer1();
	strcpy(out, (const char *)getNsubShop()->items[p[1]].data + offset);
	self->setString(out, p[2]);
	return 0;
}
static cell n_sysDLCGetItemName(AMX *, const cell *p) { return itemString(p, 0x24); }            // 0x00328254
static cell n_sysDLCGetItemDescLong(AMX *, const cell *p) { return itemString(p, 0x1A4); }       // 0x00328200
static cell n_sysDLCGetItemPriceString(AMX *, const cell *p) { return itemString(p, 0x2A4); }    // 0x003282A8
static cell n_sysDLCIsItemPurchased(AMX *, const cell *p) { return getNsubShop()->items[p[1]].data[0x2F2]; }    // 0x003283A0
static cell n_sysDLCIsItemOnDevice(AMX *, const cell *p) { return getNsubShop()->items[p[1]].data[0x2F3]; }     // 0x00328358
static cell n_sysDLCIsItemPurchasable(AMX *, const cell *p) { return getNsubShop()->items[p[1]].data[0x2F5]; }  // 0x0032837C
static cell n_sysDLCIsNewArrival(AMX *, const cell *p) { return getNsubShop()->items[p[1]].data[0x2F6]; }       // 0x00328430
static cell n_sysDLCGetItemRequiredBlock(AMX *, const cell *p) { return *(cell *)(getNsubShop()->items[p[1]].data + 0x2F8); }   // 0x003282FC

// 0x001F27E0 / 0x001F2764 / 0x001F26E8 (each then runs into a helper, 0x001F2804 / 0x001F2788 / 0x001F270C):
// the release date's year, month and day, from its milliseconds (days since 0001-01-01 for
// nn::fnd::DateTime::DaysToDate).
static cell releaseDate(const cell *p, int field)
{
	s64 ms = *(s64 *)(getNsubShop()->items[p[1]].data + 0x2E8);
	int date[3];
	nn::fnd::DateTime::DaysToDate(&date[0], &date[1], &date[2], (ms + 0x395F7CFC8400LL) / 86400000 - 730119);
	return date[field];
}
static cell n_sysDLCGetItemReleaseYear(AMX *, const cell *p) { return releaseDate(p, 0); }
static cell n_sysDLCGetItemReleaseMonth(AMX *, const cell *p) { return releaseDate(p, 1); }
static cell n_sysDLCGetItemReleaseDay(AMX *, const cell *p) { return releaseDate(p, 2); }

// 0x00328160: the account's balance as a text (three parts of the balance's price, "%s%s%s").
static cell n_sysDLCGetBalanceString(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char *out = getAmxScratchBuffer1();
	NsubShop *shop = getNsubShop();
	char text[0x80];
	snprintf(text, 0x7F, "%s%s%s", shop->balanceText[0], shop->balanceText[1], shop->balanceText[2]);
	strcpy(out, text);
	self->setString(out, p[1]);
	return 0;
}

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
static cell n_sysEnableHomeButton(AMX *, const cell *p) { System::enableHomeButton(p[1] != 0); return 0; }   // 0x0032878C
static cell n_sysEnableSleep(AMX *, const cell *p) { System::enableSleep(p[1] != 0); return 0; }             // 0x003287B0
static cell n_sysIsHomeButtonEnabled(AMX *, const cell *) { return System::s_homeButtonEnabled; }           // 0x002ECFEC
static cell n_sysIsSleepEnabled(AMX *, const cell *) { return System::s_sleepEnabled; }                     // 0x002ECE50
static cell n_sysIsPaused(AMX *, const cell *) { return System::s_paused; }                                 // 0x0024DE00
static cell n_sysSetPaused(AMX *, const cell *p) { System::setPaused(p[1] != 0); return 0; }                // 0x0032A834
static cell n_sysSetSaving(AMX *, const cell *p) { System::setSaving(p[1] != 0); return 0; }                // 0x0032A854
// 0x0032A7B0: this script keeps running while the game is paused.
static cell n_sysSetIgnorePause(AMX *, const cell *) { AMXLoader::getCurrentLoader()->ignorePause = true; return 0; }
static cell n_sysSetFakePushPowerButton(AMX *, const cell *) { System::setFakePushPowerButton(); return 0; }  // 0x0032A6C0
static cell n_sysShowErrEULA(AMX *, const cell *p) { System::showErrEULA(p[1]); return 0; }                 // 0x0032A88C
static cell n_sysShowExtraPadCalibration(AMX *, const cell *) { System::showExtraPadCalibration(); return 0; }   // 0x0032A8A0
static cell n_sysJumpToSystemMenu(AMX *, const cell *) { return 0; }                                        // 0x00329548
static cell n_sysSaveIsEnabled(AMX *, const cell *) { return 1; }                                           // 0x002F3C68
static cell n_sysGetBuildType(AMX *, const cell *) { return 0; }                                            // 0x003288B0: retail

// The US parental control (COPPA). 0x00329534: the console's region supports it; 0x00328944: 0 not
// supported (or the parental control is off), 1 restricted (its "COPPA" flag), 2 supported and free;
// 0x002ECE3C / 0x002ED014: the flags System read at start (PIN given, photo exchange restricted).
static cell n_sysIsCoppaSupported(AMX *, const cell *) { bool b; nn::cfg::IsCoppacsSupported(&b); return b; }
static cell n_sysGetCoppaRestriction(AMX *, const cell *)
{
	nn::cfg::ParentalControlInfo info;          // config blocks 0xC0001 (0x14 bytes) and 0xC0000 (0xC0)
	bool supported;
	if (!info.enabled || (nn::cfg::IsCoppacsSupported(&supported), !supported))
		return 0;
	return (info.restrictions & 1) && info.coppacsRestricted ? 1 : 2;
}
static cell n_sysIsCoppaPINAuth(AMX *, const cell *) { return System::s_coppaPINAuthorized; }               // 0x0038EBA0
static cell n_sysIsRestrictPhotoExchange(AMX *, const cell *) { return System::s_restrictPhotoExchange; }    // 0x0038EB9F
static cell n_sysAuthCoppaPIN(AMX *, const cell *) { System::authCoppaPIN(); return 0; }                    // 0x00327C74
static cell n_sysJumpToParentalControlCoppa(AMX *, const cell *) { System::jumpToParentalControlCoppa(); return 0; }   // 0x00329538

// 0x002ED118 sysGetYear, 0x002ED144 sysGetMonth, 0x002ED0EC sysGetHour, 0x002ED1D8 sysGetMinute: 4-byte
// thunks into nn::fnd::DateTime::GetNow() and the field's getter.

// ---- the Mii (facesystem.cpp) ----------------------------------------------------------------------------

// 0x00176D50, running into FaceSystem::isMiiDataFormatted: the database was just formatted (once).
static cell n_sysIsMiiDataFormatted(AMX *, const cell *) { return FaceSystem::isMiiDataFormatted(); }
static cell n_sysResetMii(AMX *, const cell *) { FaceSystem::reset(); return 0; }                           // 0x003298E4

// 0x0032A934: sysUpdateMii(mii[], index, name[], ..., select): the player's Mii, from the Mii selector
// applet when `select`; its name (UTF-8) into name[].
static cell n_sysUpdateMii(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	cell *mii = self->getAddr(p[1], 0);
	char name[0x60] = {};
	bool ok = p[6] ? FaceSystem::showMiiSelect(mii, p[2], name, sizeof(name))
	               : FaceSystem::updateMii(mii, p[2], name, sizeof(name), p[4] != 0);
	self->setString(name, p[3]);
	return ok;
}

// 0x00329180: sysGetStoreDataName(mii[], name[], ...): the name in a Mii's data.
static cell n_sysGetStoreDataName(AMX *, const cell *p)
{
	AMXLoader *self = AMXLoader::getCurrentLoader();
	char name[0x60] = {};
	bool ok = FaceSystem::getStoreDataName(self->getAddr(p[1], 0), name, sizeof(name), p[3] != 0, p[4] != 0);
	self->setString(name, p[2]);
	return ok;
}

// 0x0032A7C8: sysSetMiiStoreData(mii[], player, ...); 0x0032A64C sysSendMii(...): its arguments, as they
// are, to FaceSystem::sendMii (the count from the params header).
static cell n_sysSetMiiStoreData(AMX *, const cell *p) { FaceSystem::setStoreData(AMXLoader::getCurrentLoader()->getAddr(p[1], 0), p[2], p[3] != 0); return 0; }
static cell n_sysSendMii(AMX *, const cell *p) { int n = p[0] / 4; FaceSystem::sendMii(&p[1], n - 1, p[n]); return 0; }

// ---- debug natives left empty in the retail build ----------------------------------------------------

// 0x00328578: sysDebug(n) logs "sysDebug(%d)" (line 1105, compiled out); 0x00328770 sysDumpProfile(on),
// 0x00329878 sysQueueResources(name[]) and 0x003298C8 sysReadTimerProfileLast(profile, i) read their
// arguments for a log that is gone. All return 0.
static cell n_sysDebug(AMX *, const cell *) { return 0; }
static cell n_sysDumpLog(AMX *, const cell *) { return 0; }                     // 0x00328738
static cell n_sysEnableLogging(AMX *, const cell *) { return 0; }               // 0x003287A8
static cell n_sysPrintStats(AMX *, const cell *) { return 0; }                  // 0x003297F8
static cell n_sysCheckMessages(AMX *, const cell *) { return 0; }               // 0x003280C4
static cell n_sysResetSystem(AMX *, const cell *) { return 0; }                 // 0x003298F4
static cell n_sysResourcesBusy(AMX *, const cell *) { return 0; }               // 0x00329904
static cell n_sysGetAMXProfiles(AMX *, const cell *) { return 0; }              // 0x00328850
static cell n_sysGetLayoutProfiles(AMX *, const cell *) { return 0; }           // 0x00329038
static cell n_sysGetTimerProfiles(AMX *, const cell *) { return 0; }            // 0x002F2180
static cell n_sysGetFrameTime(AMX *, const cell *) { return 0; }                // 0x00328D30
static cell n_sysStartTimer(AMX *, const cell *) { return 0; }                  // 0x0032A910
static cell n_sysStopTimer(AMX *, const cell *) { return 0; }                   // 0x0032A918
static cell n_sysReadTimer(AMX *, const cell *) { return 0; }                   // 0x003298C0
static cell n_sysResetTimer(AMX *, const cell *) { return 0; }                  // 0x003298FC
// 0x00328F58 sysGetGlobalIdx / 0x0032A7A8 sysSetGlobalIdx: 0; 0x00328F30 sysGetGlobalArrayIdx / 0x0032A780
// sysSetGlobalArrayIdx: resolve their array argument and return 0 (indexed globals, never written).
static cell n_sysGetGlobalIdx(AMX *, const cell *) { return 0; }
static cell n_sysSetGlobalIdx(AMX *, const cell *) { return 0; }
static cell n_sysDumpModels(AMX *, const cell *) { for (int i = 0; i < 4; i++) Renderer::getRenderer(i)->dumpModels(); return 0; }   // 0x00328740
static cell n_sysPrintResourceList(AMX *, const cell *) { Resource::printResourceList(); return 0; }        // 0x003297E8
// 0x00327C84 / 0x003287CC: AMXProfiler::beginProfile / endProfile of the named point (amxutils.cpp).
static cell n_sysBeginProfilePoint(AMX *, const cell *p) { char n[384]; AMXLoader::getCurrentLoader()->getString(n, p[1]); AMXProfiler::beginProfile(n); return 0; }
static cell n_sysEndProfilePoint(AMX *, const cell *p) { char n[384]; AMXLoader::getCurrentLoader()->getString(n, p[1]); AMXProfiler::endProfile(n); return 0; }

// ---- the engine's side of the globals ----------------------------------------------------------------

// 0x00249824: a global's value from C++ (main.cpp, the network...): 0 when it does not exist.
cell amxSysGetGlobal(const char *name)
{
	for (Global *g = s_integers[hashName(name)]; g != nullptr; g = g->next)
		if (strcmp(g->name, name) == 0)
			return g->value;
	return 0;
}

// ---- MemStream (the save's stream; vtable 0x00376C10) ------------------------------------------------
// {vtable, size +4, position +8, data +0xC}.
bool MemStream::eof() { return size <= position; }          // 0x002F6B90
u32 MemStream::getLength() { return size; }                  // 0x002F6BE4
// 0x002F6BA4: nothing is written past the end.
void MemStream::write(const void *src, u32 n)
{
	if (position + n <= size) {
		memcpy(data + position, src, n);
		position += n;
	}
}
// 0x001DA50C: past the end, the stream may refill (vtable +0x1C); if not, only what is left is read.
u32 MemStream::read(void *dest, u32 n)
{
	if (position + n > size && !refill(n))
		n = remaining();                    // vtable +0x24
	memcpy(dest, data + position, n);
	position += n;
	return n;
}

// 0x0030D9D0 __sti___10_amxsys_cpp: the two hash tables emptied, the mode script "", and the module's other
// statics.
// 0x00328948: sysGetDirectoryListing(path[], &bxml, stripExtension): the files of "rom:/<path>" as a new
// BXML document (<path><model name="..."/>...</path>), its address returned in the cell — a debug helper.
