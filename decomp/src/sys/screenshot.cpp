// source/sys/screenshot.cpp (screenshot.o) and source/sys/sdcard.cpp (sdcard.o): the 3D photos of the album
// (the system's image database on the SD card, imgdb), taken from the top screen.
//
// Reconstructed by hand from decomp/raw/source/sys/{screenshot,sdcard}.cpp and the disassembly. Not
// compilable on its own. The writing thread is FlashMemory's (savedata.cpp: ScreenshotThread).

static imgdb::JpegSaver *s_jpeg;        // 0x0038EB60 a 2D photo
static imgdb::MpSaver *s_mpo;           // 0x0038EB64 a 3D photo (MPO: both eyes)

// 0x00110F94
void Screenshot::init()
{
	s_jpeg = new imgdb::JpegSaver();
	s_mpo = new imgdb::MpSaver();
}

// 0x00178BA4: the top screen (400x240, format 7) of one eye, or both when the 3D slider allows stereo.
// Each photo carries the game's unique id, the screenshot flag and, as its maker note, the text "This is
// UserMakerNote!". An error of the image database goes to the
// mode script's @dialogCheckImgDbError(code). Without a writable SD card nothing is written (true).
bool Screenshot::performWrite(const void *left, const void *right, u32 size)
{
	generateCRC(left, size);                                   // (for a log)
	bool stereo = nngxIsStereoVisionAllowed();
	if (!nn::fs::IsSdmcInserted() || !nn::fs::IsSdmcWritable())
		return true;
	static const char note[] = "This is UserMakerNote!";
	int error;
	if (!stereo) {
		s_jpeg->SetRaw(left, 400, 240, 7);
		s_jpeg->SetTitleUniqueId(System::getUniqueId());
		s_jpeg->SetScreenshotFlag(true);
		s_jpeg->SetUserMakerNote(note, sizeof note);
		error = s_jpeg->Save();
	} else {
		s_mpo->SetRaw(left, right, 400, 240, 7);
		s_mpo->SetTitleUniqueId(System::getUniqueId());
		s_mpo->SetScreenshotFlag(true);
		s_mpo->SetUserMakerNote(note, sizeof note);
		error = s_mpo->Save();
	}
	if (error == 0)
		return true;
	// "[Screenshot::performWrite] Error! Result = %d"
	AMXLoader *mode = AMXLoader::uidToAmx(UID_MODE);
	int index = mode->findPublic("@dialogCheckImgDbError");
	if (index >= 0) {
		AMXState state;
		mode->freezeState(&state);
		mode->pushArg(error);
		mode->callFunction(index);
		mode->thawState(&state);
	}
	return false;
}

// 0x00178F14 / 0x00178F54: the save data layer's "mounted" flag stands for the card while a photo is
// written (FlashMemory's busy state and thread are shared).
bool Screenshot::open()
{
	if (!nn::fs::IsSdmcInserted() || !nn::fs::IsSdmcWritable())
		return false;
	if (!SaveData::isMounted())
		SaveData::setMounted(true);
	return true;
}

bool Screenshot::close() { SaveData::setMounted(false); return true; }

// sdcard.cpp, 0x002EC844: "sdmc:/" + name (TextData's override). Its other strings ("SD ACCESS: Mount Fail,
// ...", "[SDCard::performWrite] Write of %d bytes failed: %d, returning false!") lost their code.
void SDCard::getPath(char path[128], const char *name)
{
	strncpy(path, "sdmc:/", 128);
	strncat(path, name, 128);
}
