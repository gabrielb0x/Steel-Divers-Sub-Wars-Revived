// source/amx/amxsys.cpp (amxsys.o), in part: the script globals, the save natives and the shop natives.
//
// Reconstructed by hand from decomp/raw/source/amx/amxsys.cpp and the disassembly. Not compilable on its
// own. The other 140 natives of amxsys (system, Mii, friends, sound...) are still only in decomp/raw/.

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
