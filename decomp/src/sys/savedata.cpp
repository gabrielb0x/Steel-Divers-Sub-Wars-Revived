// source/sys/savedata.cpp (savedata.o) and source/sys/flashmemory.cpp (flashmemory.o): the save data archive.
//
// Reconstructed by hand from decomp/raw/source/sys/{savedata,flashmemory}.cpp and the disassembly. Not
// compilable on its own. The format of the only save file, "save", is written by the scripts' natives
// (decomp/src/amx/amxsys.cpp, docs/formats.md#save); this layer adds a CRC-32 in front of it and
// writes it from a thread, so that the game keeps running while the card is written.
// Left out: Screenshot (the 3D photos of the album, imgdb) and the AMX events (amxEvent*), which call the
// current mode's script to show the error dialogs.

// ---- state (0x0038EB40..0x0038EB4C) ----
static bool s_busy;                  // 0x0038EB40: a write (or a screenshot) is running: sysSaveDataBusy
static bool s_mounted;               // 0x0038EB41: "data:" is mounted
static bool s_dirty;                 // 0x0038EB42: something was written: commit before unmounting
static bool s_debugFormat;           // 0x0038EB43: sysSaveDebugFormat (unused by the retail scripts)
static nn::os::Thread s_thread;      // 0x0038EB48: SaveThread or ScreenshotThread (priority 0x14, 4 KB stack)

// 0x001DF658: "data:/" + name.
void FlashMemory::getPath(char path[0x80], const char *name)
{
	strncpy(path, "data:/", 0x80);
	strncat(path, name, 0x80);
}

// 0x00218E0C: mounts the save data archive. A save that cannot be mounted is formatted:
//   FS errors 340..359 (never formatted: the first start)                  silently
//   FS errors 360..399 (damaged: bad format, verification failed)          and "mode.saveformatted" = 1, so
//                                                                          that mode_title tells the player
// then mounted again. SaveData::open (0x00218E08) is the same function with retry = false.
bool FlashMemory::open(bool retry)
{
	bool formatted = false;
	Result result = nn::fs::MountSaveData("data:");
	if (result.IsFailure()) {
		if (result.module() == nn::fs && 340 <= result.description() && result.description() < 360) {
			nn::fs::FormatSaveData(0x40, 0, true);        // 64 files, no directory, duplicated (journaled)
			formatted = true;
		} else if (result.module() == nn::fs && 360 <= result.description() && result.description() < 400) {
			nn::fs::FormatSaveData(0x40, 0, true);
			amxSysSetGlobal("mode.saveformatted", 1);
			formatted = true;
		}
		amxEventLoadSaveMountFail(formatted ? 0 : -1);
		SaveData::setMounted(false);
		if (!formatted) {
			return false;
		}
	} else {
		SaveData::setMounted(true);
	}
	if (formatted && !retry) {
		SaveData::close();
		return open(true);
	}
	return SaveData::isMounted();
}

// 0x002F39BC (FlashMemory::close 0x0021C434 and SaveData::close 0x0021C430 run into it): commits the
// archive if something was written (the journaled save becomes the current one), then unmounts it.
bool SaveData::close()
{
	if (s_dirty) {
		nn::fs::CommitSaveData("data:");
		s_dirty = false;
	}
	Result result = nn::fs::Unmount("data:");
	if (result.IsSuccess()) {
		s_mounted = false;
	} else {
		amxEventLoadSaveUnmountFail(result.description());
	}
	return result.IsSuccess();
}

// 0x001DF6C0 (SaveData::format 0x001DF6A8 closes first and runs into it): the current mode's script resets
// its save globals (public @saveFormat, save.inc), then the archive is formatted.
bool FlashMemory::format(bool tellPlayer)
{
	if (AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE)) {
		nn::fs::FormatSaveData(0x40, 0, true);
		AMXState state;
		mode->freezeState(&state);
		mode->callFunction(mode->findPublic("@saveFormat"));
		mode->thawState(&state);
	}
	if (tellPlayer) {
		amxSysSetGlobal("mode.saveformatted", 1);
	}
	Result result = nn::fs::FormatSaveData(0x40, 0, true);
	if (result.IsFailure()) {
		amxEventLoadSaveFormatFail(result.description());
	}
	return result.IsSuccess();
}

// 0x002F34A8: reads a whole file of the archive into a new buffer, without its CRC. A file whose CRC does
// not match is a damaged save: the archive is formatted and the script told (amxEventLoadCorruptData).
bool SaveData::read(const char *name, u8 **data, u32 *size)
{
	if (!FlashMemory::open(false)) {
		FlashMemory::close();
		return false;
	}
	char path[0x80];
	FlashMemory::getPath(path, name);
	nn::fs::FileInputStream file;
	Result result = file.TryInitialize(path);
	if (result.IsFailure()) {
		handleIOError(result);
		amxEventLoadOpenFail(result.description());            // no save yet: the scripts start from defaults
		FlashMemory::close();
		return false;
	}
	*size = file.GetSize();
	if (*size == 0) {
		amxEventLoadReadFail(1);
		file.Finalize();
		FlashMemory::close();
		return false;
	}
	*data = new u8[*size];
	s32 read;
	result = file.TryRead(&read, *data, *size);
	if (result.IsFailure() || read < *size) {
		handleIOError(result);
		amxEventLoadReadFail(result.description());
	} else {
		u32 crc = *(u32 *)*data;
		*data += 4;
		*size -= 4;
		if (crc == generateCRC(*data, *size)) {               // the CRC-32 of zlib (crc.cpp)
			file.Finalize();
			FlashMemory::close();
			return read != 0;
		}
		FlashMemory::close();
		FlashMemory::format(true);
		amxEventLoadCorruptData();
	}
	file.Finalize();
	FlashMemory::close();
	return false;
}

// 0x002F313C: sysSaveDataSave: hands the buffer to SaveThread and returns; sysSaveDataBusy() says when it
// is written. Used for the single file "save" (and "screenshot" through takeScreenshot).
bool SaveData::writeandclose(const char *name, const u8 *data, u32 size)
{
	if (!FlashMemory::open(false)) {
		return false;
	}
	SaveJob *job = new SaveJob;                               // 0x30 bytes: name (0x20), data, size
	strncpy(job->name, name, sizeof(job->name));
	job->data = data;
	job->size = size;
	s_busy = true;
	s_thread.TryStartUsingAutoStack(SaveThread, job, 0x1000, 0x14);
	return true;
}

// 0x001710D0: the save thread, under the scripts' mutex (amxSysGetMutex): the globals cannot change meanwhile.
static void SaveThread(SaveJob *job)
{
	nn::os::Mutex *mutex = amxSysGetMutex(0);
	mutex->Lock();
	bool ok = FlashMemory::performWrite(job->name, job->data, job->size);
	s_busy = false;
	FlashMemory::close();                                     // commits
	if (ok) {
		amxEventSaveWriteSuccess();
	}
	mutex->Unlock();
	System::setSaving(false);                                 // the HOME and power buttons wait for this
	s_thread.Finalize();
}

// 0x00179870: writes "data:/<name>" = u32 CRC-32 of the data, then the data. If the file cannot be opened,
// the archive is formatted (the script's @saveFormat first) and the open retried, three times at most.
bool FlashMemory::performWrite(const char *name, const u8 *data, u32 size)
{
	u32 crc = generateCRC(data, size);
	char path[0x80];
	getPath(path, name);
	nn::fs::FileStream file;
	Result result;
	for (int attempt = 0; attempt < 3; attempt++) {
		result = file.TryInitialize(path, nn::fs::OPEN_MODE_WRITE | nn::fs::OPEN_MODE_CREATE);
		if (result.IsSuccess()) {
			break;
		}
		if (AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE)) {     // as in FlashMemory::format
			nn::fs::FormatSaveData(0x40, 0, true);
			AMXState state;
			mode->freezeState(&state);
			mode->callFunction(mode->findPublic("@saveFormat"));
			mode->thawState(&state);
		}
		if (nn::fs::FormatSaveData(0x40, 0, true).IsFailure()) {
			amxEventLoadSaveFormatFail(...);
		}
	}
	if (result.IsFailure()) {
		amxEventSaveOpenFail(result.description());
		return false;
	}
	file.SetSize(size + 4);
	s32 written;
	if (file.TryWrite(&written, &crc, 4, true).IsFailure() || written < 4) {
		amxEventSaveWriteFail(4 - written);
		return false;
	}
	if (file.TryWrite(&written, data, size, true).IsFailure() || written < size) {
		amxEventSaveWriteFail(size - written);
		return false;
	}
	file.Finalize();
	SaveData::setDirty();
	return true;
}

// 0x002F3350: sysSaveDataClear: deletes a file of the archive ("save" when the player erases everything).
bool SaveData::rm(const char *name)
{
	if (!FlashMemory::open(false)) {
		return false;
	}
	char path[0x80];
	FlashMemory::getPath(path, name);
	Result result = nn::fs::TryDeleteFile(path);
	if (result.IsFailure()) {
		handleIOError(result);
	}
	return result.IsSuccess();
}

// 0x002F3A20: size of a file of the archive (0 if absent).
// 0x002F3498 busy() = s_busy, 0x002F3C74 isMounted() = s_mounted, 0x00219134 setMounted(),
// 0x002F3C54 setDirty() = s_dirty = true, 0x002F3C6C isEnabled() = true, 0x002F3218 setDebugFormat().
