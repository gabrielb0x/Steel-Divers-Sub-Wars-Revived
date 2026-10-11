// source/sys/resource.cpp (resource.o): reading the game's files. A file is read whole into memory once,
// and kept in a "stock" (a list of the files read): the level stock, emptied when a mode starts
// (resetStock, main.cpp), or the system stock, kept for the whole game (the effects' shaders and textures
// load there: useSysStock() ... useStock(previous)).
//
// Reconstructed by hand from decomp/raw/source/sys/resource.cpp and the disassembly. Not compilable on its
// own. A file that cannot be read stops the game with the system's fatal error screen.

struct ResourceData {                   // 0xB0 bytes, vtable 0x00376DA4
	nn::fs::FileInputStream file;       // +0x04 (open while reading)
	bool loaded;                        // +0x18
	ResourceData *next;                 // +0x1C
	char path[128];                     // +0x20 "rom:/..." (the key of the stock)
	void *data;                         // +0xA0
	u32 size;                           // +0xA4
	bool relocated;                     // +0xA8 BXML::load turned its offsets into pointers (once)
	bool skipped;                       // +0xAC skipped by the search; nothing sets it
};

// ---- module state (0x0038EB18..0x0038EB2C) -------------------------------------------------------------
static ResourceData *s_levelStock;      // 0x0038EB18
static ResourceData *s_sysStock;        // 0x0038EB1C
static ResourceData **s_stock = &s_levelStock;   // 0x0038EB20 where new files go
static u32 s_loaded;                    // 0x0038EB24 files read since resetStock
static const char *s_archive;           // 0x0038EB28 setArchiveName: null for "rom:"

// 0x0010DD10: when a mode starts (the memory of the level stock goes with the mode's heap group).
void Resource::resetStock()
{
	s_levelStock = nullptr;
	s_loaded = 0;
}

ResourceData **Resource::useStock(ResourceData **stock) { ResourceData **old = s_stock; s_stock = stock; return old; }  // 0x00252A9C
ResourceData **Resource::useSysStock() { ResourceData **old = s_stock; s_stock = &s_sysStock; return old; }            // 0x00252AE8
void Resource::setArchiveName(const char *archive) { s_archive = archive; }   // 0x002F30AC (dlc.cpp: "content:")

// 0x00241E7C: "rom:/" + name, or "<archive>/" + name.
static void getPath(char path[128], const char *name)
{
	strncpy(path, s_archive != nullptr ? s_archive : "rom:/", 128);
	if (s_archive != nullptr)
		strncat(path, "/", 128);
	strncat(path, name, 128);
}

// 0x0013A610: a file already read, in the system stock then the level stock.
static ResourceData *findStockAbsPath(const char *path)
{
	for (ResourceData **stock : {&s_sysStock, &s_levelStock})
		for (ResourceData *r = *stock; r != nullptr; r = r->next)
			if (!r->skipped && strcmp(r->path, path) == 0)
				return r;
	return nullptr;
}

// 0x0013A408: reads a whole file (aligned as asked) from the current allocator. "Unable to open file: %s";
// then the size and the read failing call nn::err::ThrowFatalErrAll (the console's fatal error screen).
static void loadDataSync(ResourceData *r, const char *path, int alignment)
{
	strncpy(r->path, path ? path : "", 128);
	r->loaded = false;
	wchar_t wide[264];
	utf8ToUtf16(wide, r->path);                                // 0x0024A050 / 0x0024A084, character by character
	r->file.TryInitialize(wide, nn::fs::OPEN_MODE_READ);
	s64 size;
	nn::Result result = r->file.TryGetSize(&size);             // 0x00249F64
	if (result.IsFailure())
		nn::err::CTR::ThrowFatalErrAll(result);
	r->size = size;
	r->data = allocAligned(r->size, alignment);
	r->loaded = true;
	result = r->file.TryRead(nullptr, r->data, r->size);
	if (result.IsFailure())
		nn::err::CTR::ThrowFatalErrAll(result);
	r->file.Finalize();
	s_loaded++;
}

// 0x00241D54: the file of a full path, read if needed into the current stock (from the system heap when
// the current stock is the system's).
ResourceData *Resource::getResourceAbsPath(const char *path, int alignment)
{
	ScopedHeap heap(System::getSysHeap(), s_stock == &s_sysStock);
	ResourceData *r = findStockAbsPath(path);
	if (r == nullptr) {
		r = new ResourceData();
		loadDataSync(r, path, alignment);
		r->next = *s_stock;
		*s_stock = r;
	} else if (r->data == nullptr) {
		loadDataSync(r, path, 0x80);
	}
	return r;
}

// 0x00252978: the data itself, or (copy) a copy of its own, aligned as asked.
void *Resource::getData(ResourceData *r, bool copy, int alignment)
{
	if (!copy)
		return r->data;
	void *data;
	{
		ScopedHeap heap(System::getSysHeap(), s_stock == &s_sysStock);
		data = allocAligned(r->size, alignment);
	}
	memcpy(data, r->data, r->size);
	return data;
}

// 0x0025011C: a file of the game by its name ("shaders/...", "bxml/...").
void *Resource::getFile(const char *name, bool copy, int alignment)
{
	char path[128];
	getPath(path, name);
	return getData(getResourceAbsPath(path, alignment), copy, alignment);
}

// 0x00252AB4: read it without using it yet.
void Resource::getResource(const char *name, int alignment)
{
	char path[128];
	getPath(path, name);
	getResourceAbsPath(path, alignment);
}

// 0x00117A00: the same as a memory stream (vtable 0x00376C10: its size, its data, position 0).
MemStream Resource::getFileMem(const char *name, bool copy, int alignment)
{
	char path[128];
	getPath(path, name);
	ResourceData *r = getResourceAbsPath(path, alignment);
	return MemStream(getData(r, copy, alignment), r->size);
}

// 0x0010DD28: getResourceAbsPath with a UTF-16 path (narrowed character by character).
ResourceData *Resource::getResourceAbsPath(const wchar_t *path, int alignment)
{
	char narrow[129];
	int i = 0;
	do
		narrow[i] = (char)path[i];
	while (path[i] != 0 && ++i < 128);
	return getResourceAbsPath(narrow, alignment);
}

// 0x0010DBA0: does the file exist (can it be opened)?
bool Resource::fileExists(const char *name)
{
	char path[128];
	getPath(path, name);
	wchar_t wide[264];
	utf8ToUtf16(wide, path);
	nn::fs::FileInputStream file;
	return file.TryInitialize(wide).IsSuccess();
}

// 0x002F30BC: a log of every file of the level stock (the log is gone).
void Resource::printResourceList() {}
