// source/sys/facesystem.cpp (facesystem.o): the Miis. The player's own (Mii selector applet, or the
// console's personal Mii), their icons (rendered by the Mii library, CFL, into a 128x128 texture), and the
// Miis of the other players of a session: each console sends its Mii with its player's statistics, the
// others decode it in a thread and hand it to the game_state script.
//
// Reconstructed by hand from decomp/raw/source/sys/facesystem.cpp and the disassembly. Not compilable on its
// own. The variable names sProcessedMii, sMiiHead and sMiiTail are the developers' (their logs).

// ---- module state (0x0038EA10..0x0038EA4C; 0x00593C68..0x00595648) -------------------------------------
static bool s_iconPending;              // 0x0038EA10 createIcon: draw it at the next update
static bool s_iconFromMine;             // 0x0038EA11 the icon is of s_myStoreData (else s_otherStoreData)
static u32 sMiiHead;                    // 0x0038EA14 next slot for a Mii received (receiveMiiCB)
static u32 sProcessedMii;               // 0x0038EA18 next slot to decode (MiiThread)
static u32 sMiiTail;                    // 0x0038EA1C next slot to hand to the script (setPlayerMii)
static bool s_threadRunning;            // 0x0038EA12
static bool s_databaseFormatted;        // 0x0038EA20 CFL_InitRes formatted the Mii database
static void *s_resource;                // 0x0038EA24 the Mii library's resources (system heap)
static void *s_work;                    // 0x0038EA28 its work memory (device heap)
static GLuint s_program;                // 0x0038EA2C shaders/miirender.shbin
static GLuint s_texture, s_framebuffer, s_depth;  // 0x0038EA30.. the icon's target, 128x128
static void *s_iconTarget;              // 0x0038EA3C
static GLint s_texturePhysical;         // 0x0038EA40
static nn::os::Thread s_thread;         // 0x0038EA44

static CFLStoreData s_myStoreData;      // 0x00593C68 0x60 bytes: this player's Mii
static CFLStoreData s_received[16];     // 0x00593CC8 the Miis received, decoded
static CFLStoreData s_otherStoreData;   // 0x005942C8
static CFLNetInformation s_netInfo[16]; // 0x00594328
static u32 s_source[16];                // 0x005945A8 the sender of each slot
static bool s_decoded[16];              // 0x005945E8
static CFLNetPacket s_packets[16];      // 0x005945F8 0xF4 bytes each, as received
static CFLNetPacket s_outgoing;         // 0x00595538 this console's Mii, as sent
// A packet: the Mii library's own part, then 26 cells of the game's from +0x88 (statistics), and their
// count at +0xF0.

// 0x0010180C: the Mii library (its database may have to be formatted: isMiiDataFormatted), the icon's
// render target and shader, the 16 receiving slots. Special Miis are enabled (key 0x13DE28CF).
void FaceSystem::init()
{
	{
		ScopedHeap heap(System::getSysHeap());
		u32 size = CFL_GetResourceBufferSize();
		s_resource = alloc(size, 4);
		CFL_LoadResource(s_resource);
		ScopedHeap device(System::getDeviceHeap());
		s_work = alloc(CFL_GetWorkSize(0), 4);
		s_databaseFormatted = CFL_InitRes(s_work, s_resource, size, 0);
	}
	glGenTextures(1, &s_texture);
	glGenFramebuffers(1, &s_framebuffer);
	glGenRenderbuffers(1, &s_depth);
	glBindTexture(GL_TEXTURE_2D, s_texture);
	glBindFramebuffer(GL_FRAMEBUFFER, s_framebuffer);
	glBindRenderbuffer(GL_RENDERBUFFER, s_depth);
	glTexImage2D(GL_TEXTURE_2D | NN_GX_MEM_VRAMA, 0, GL_RGBA_NATIVE_DMP, 128, 128, 0, GL_RGBA_NATIVE_DMP,
	             GL_UNSIGNED_BYTE, nullptr);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, s_texture, 0);
	glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8_EXT, 128, 128);
	glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, s_depth);
	glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_DATA_ADDR_DMP, &s_texturePhysical);
	initShader();
	s_iconParameters = {0x8058, 1, 0, 0, 0, 0};         // 0x00595630..
	for (int i = 0; i < 16; i++)
		CFL_InitNetPacket(&s_packets[i], 1);
	CFL_InitNetPacket(&s_outgoing, 1);
	for (int i = 0; i < 16; i++)
		CFL_InitNetInformation(&s_netInfo[i], &s_packets[i], 0, 16, 1);
	CFLi_EnableSpecialMii(0x13DE28CF);
}

// 0x00108290: the Mii library draws with the game's own vertex shader.
void FaceSystem::initShader()
{
	void *binary = Resource::loadFile("shaders/miirender.shbin");
	s_program = glCreateProgram();
	GLuint shader = glCreateShader(GL_VERTEX_SHADER);
	glShaderBinary(1, &shader, GL_PLATFORM_BINARY_DMP, binary);
	glAttachShader(s_program, shader);
	glAttachShader(s_program, GL_DMP_FRAGMENT_SHADER_DMP);
	glBindAttribLocation(s_program, 0, "aPosition");
	glBindAttribLocation(s_program, 1, "aNormal");
	glBindAttribLocation(s_program, 2, "aTexCoord");
	glLinkProgram(s_program);
	glUseProgram(s_program);
	CFL_SetProgramContext(s_program, glGetUniformLocation(s_program, "uProjMtx"),
	                      glGetUniformLocation(s_program, "uPosMtx"), glGetUniformLocation(s_program, "uNrmMtx"),
	                      glGetUniformLocation(s_program, "uTexMtx"), 0,
	                      glGetAttribLocation(s_program, "aPosition"), glGetAttribLocation(s_program, "aNormal"),
	                      glGetAttribLocation(s_program, "aTexCoord"), GL_TEXTURE0);
}

// 0x00176D54: once, after init.
bool FaceSystem::isMiiDataFormatted()
{
	bool formatted = s_databaseFormatted;
	s_databaseFormatted = false;
	return formatted;
}

// ---- icons ---------------------------------------------------------------------------------------------

// 0x001769EC: the Mii to draw next: this player's (mine) or another one.
void FaceSystem::setStoreData(const void *data, u32 size, bool mine)
{
	s_iconFromMine = mine;
	memcpy(mine ? &s_myStoreData : &s_otherStoreData, data, size);
}

// 0x001769A4: asks for an icon (drawn at the next update, into `target`), with its size and background.
void FaceSystem::createIcon(u16 width, u16 height, void *target, const u8 background[4])
{
	s_iconParameters.background = *(const u32 *)background;
	s_iconPending = true;
	s_iconTarget = target;
	s_iconParameters.width = width;
	s_iconParameters.height = height;
	nngxGetPhysicalAddr(s_texturePhysical);
}

// 0x00176C80
const CFLStoreData *FaceSystem::getMyStoreData() { return &s_myStoreData; }

// ---- every frame ---------------------------------------------------------------------------------------

// 0x00101A4C: the icon asked for, then the Miis received: on even frames the decoding thread starts when a
// Mii waits for it; on odd frames one decoded Mii goes to the script.
void FaceSystem::update()
{
	if (s_iconPending) {
		nngxClearCmdlist();
		glBindFramebuffer(GL_FRAMEBUFFER, s_framebuffer);
		glBindRenderbuffer(GL_RENDERBUFFER, s_depth);
		glUseProgram(s_program);
		nngxValidateState(NN_GX_STATE_ALL, GL_TRUE);
		CFL_MakeIcon(s_texturePhysical, s_iconFromMine ? 4 : 5, s_iconFromMine ? &s_myStoreData : &s_otherStoreData,
		             0, s_iconTarget, &s_iconParameters);
		nngxUpdateState(NN_GX_STATE_ALL);
		u32 *command = Graphics::startCommand();       // PICA registers 0x65..0x67 (scissor): 0, 0, 127x127
		command[0] = 0;
		command[1] = 0x802F0065;
		command[2] = 0;
		command[3] = 0x007F007F;
		command = nn::gr::CTR::MakeDisableAllCommand(command + 4);
		Graphics::endCommand(command);
		nngxFlush3DCommand();
		Graphics::executeCommands();
		s_iconPending = false;
	}
	if (s_threadRunning)
		return;
	if ((System::getGameFrameNum() & 1) == 0) {
		if (sProcessedMii != sMiiHead) {
			s_threadRunning = true;
			s_thread.TryStartUsingAutoStack(MiiThread, 0, 0x1000, 0x14);
		}
	} else if (sMiiTail != sProcessedMii) {
		setPlayerMii();
	}
}

// ---- the other players' Miis ---------------------------------------------------------------------------

void FaceSystem::registerListeners() { DataStreamer::registerListener(receiveMiiCB, 5); }  // 0x00176D40

// 0x00176E10: sysSendMii(...): this player's Mii and `count` cells (the statistics the lobby shows: games,
// distance, hits, kills, wins... see mode_lobby), to a node (0xFFFF: everybody).
void FaceSystem::sendMii(const cell *values, u32 count, u32 node)
{
	memcpy(s_outgoing.user, values, count * sizeof(cell));          // +0x88
	s_outgoing.userCount = count;                                     // +0xF0
	CFL_SetToNetPacket(&s_outgoing, 0, 4, &s_myStoreData, 0);
	DataStreamer::queueData((u8 *)&s_outgoing, sizeof s_outgoing, 5, node);
}

// 0x0017163C (DataStreamer channel 5): a Mii received is queued (16 slots), once per sender.
// "[FaceSystem::receiveMiiCB] Source node = %x, my nodeId = %x, %s = %d".
// The developers meant to skip a Mii (when its second cell is 0) according to the sender's
// "player.<node>.team" global: the name is formatted, but the global read is the one literally named
// "player.%x.team", which does not exist, so nothing is skipped.
static void receiveMiiCB(const u8 *data, u32 length, u8, u32 source)
{
	// length other than 0xF4: "facesystem received buffer length %d; expected %d" (no check)
	const CFLNetPacket *packet = (const CFLNetPacket *)data;
	char name[36];
	sprintf(name, "player.%x.team", source);
	if (packet->user[1] == 0 && amxSysGetGlobal("player.%x.team") != 0)
		return;                         // "[FaceSystem::receiveMiiCB] Skipping because %s = %d!"
	for (u32 queued : s_source)
		if (queued == source)
			return;                     // "Skipping because %x is already queued!"
	nn::os::Mutex *mutex = amxSysGetMutex(3);
	mutex->Lock();
	s_source[sMiiHead] = source;
	memcpy(&s_packets[sMiiHead], data, length);
	sMiiHead = (sMiiHead + 1) % 16;
	mutex->Unlock();
}

// 0x00107A48 (thread, priority 0x14): decodes the next Mii received ("[FaceSystem::MiiThread] ...").
static void MiiThread(void *)
{
	nn::os::Mutex *mutex = amxSysGetMutex(3);
	mutex->Lock();
	int result = CFL_SetReceivedPacket(&s_netInfo[sProcessedMii], &s_packets[sProcessedMii], 1);
	s_decoded[sProcessedMii] = (result == 0 || result == 5)
	                           && CFL_NetInfo2StoreData(&s_received[sProcessedMii], &s_netInfo[sProcessedMii], 1, 0) == 0;
	sProcessedMii = (sProcessedMii + 1) % 16;
	mutex->Unlock();
	s_thread.Finalize();
	s_threadRunning = false;
}

// 0x00106DFC: hands the next Mii to game_state (UID_GAME_STATE): @setPlayerMii(storeData[], node, cells
// 1..count of the sender's values), or @retrySetRemote() when it could not be decoded; the slot is freed.
// ("[FaceSystem::setPlayerMii] Calling game_state::@setPlayerMii with nodeId %x!")
static void setPlayerMii()
{
	AMXLoader *script = AMXLoader::uidToAmx(UID_GAME_STATE);
	if (script == nullptr)
		return;
	nn::os::Mutex *mutex = amxSysGetMutex(3);
	mutex->Lock();
	AMXState state;
	script->freezeState(&state);
	u32 slot = sMiiTail;
	if (s_decoded[slot]) {
		int index = script->findPublic("@setPlayerMii");
		if (index >= 0) {
			for (int i = s_packets[slot].userCount; i > 0; i--)
				script->pushArg(s_packets[slot].user[i]);
			script->pushArg(s_source[slot]);
			script->pushArgArray((cell *)&s_received[slot], 0x60);
			script->callFunction(index);
		}
	} else {
		int index = script->findPublic("@retrySetRemote");
		if (index >= 0)
			script->callFunction(index);
	}
	script->thawState(&state);
	memset(&s_received[slot], 0, sizeof s_received[slot]);
	s_source[slot] = 0;
	s_decoded[slot] = false;
	memset(&s_packets[slot], 0, sizeof s_packets[slot]);
	sMiiTail = (sMiiTail + 1) % 16;
	mutex->Unlock();
}

// 0x00176D78 (Network::setStatus, leaving IN_SESSION): every slot emptied.
void FaceSystem::reset()
{
	s_iconPending = false;
	sMiiHead = sProcessedMii = sMiiTail = 0;
	memset(s_received, 0, sizeof s_received);
	memset(s_source, 0, sizeof s_source);
	memset(s_decoded, 0, sizeof s_decoded);
	memset(s_packets, 0, sizeof s_packets);
}

// ---- this player's Mii ---------------------------------------------------------------------------------

// Its name, in UTF-8 (64 bytes): the Mii's nickname, or the text "playername_censored" when flag 0x20000000
// of the Mii's information is set or for a guest.
static bool miiName(const CFLStoreData *mii, int source, char name[64], bool hidden)
{
	CFLAdditionalInfo info;
	if (CFL_GetAdditionalInfo(&info, source, mii, 0, 0) == 0 && !(info.flags & 0x20000000) && !hidden) {
		convertUTF16toUTF8(info.name, name, 64);
		return true;
	}
	strcpy(name, TextData::find("playername_censored"));
	return false;
}

// 0x00176A1C: the Mii selector applet. The Mii chosen becomes
// this player's; "save.multi.isguest" says whether it is the guest. False when the player cancelled.
bool FaceSystem::showMiiSelect(void *storeData, u32 size, char name[64])
{
	miisel::Parameter parameter;    // its flags set twice in a row, the special Mii key 0x13DE28CF
	miisel::Result result;
	nngxSplitDrawCmdlist();
	nngxWaitCmdlistDone();
	miisel::StartMiiSelectApplet(&parameter, &result);
	nngxUpdateState(NN_GX_STATE_ALL);
	nngxValidateState(NN_GX_STATE_ALL, GL_TRUE);
	if (result.code != 0)
		return false;
	memcpy(storeData, &result.mii, size);
	s_iconFromMine = true;
	memcpy(&s_myStoreData, &result.mii, size);
	// "[FaceSystem::showMiiSelect] lenStoreData = %d, lenName = %d"
	miiName(&s_myStoreData, 4, name, result.isGuest);
	amxSysSetGlobal("save.multi.isguest", result.isGuest);
	return true;
}

// 0x00176E78: the console's personal Mii (the first official one of its database, CFL_SearchOfficialData),
// without the applet. False when there is none.
bool FaceSystem::updateMii(void *storeData, u32 size, char name[64], bool mine)
{
	u16 index = 0;
	if (!CFL_SearchOfficialData(&index))
		return false;
	CFL_GetStoreData(&s_myStoreData, 0, index);  // "[FaceSystem::updateMii] CFL_GetAdditionalInfo retrieved index %d!"
	memcpy(storeData, &s_myStoreData, size);
	s_iconFromMine = true;
	miiName(&s_myStoreData, mine ? 4 : 5, name, amxSysGetGlobal("save.multi.isguest") != 0);
	return true;
}

// 0x00176C8C: the name of a Mii (the player's own: source 4, another: 5).
bool FaceSystem::getStoreDataName(const CFLStoreData *mii, char name[64], bool mine, bool hidden)
{
	return miiName(mii, mine ? 4 : 5, name, hidden);
}

// 0x0024DBC4: the Mii library's exit (CFL_Exit inlined): waits for its work, frees its cache, closes its
// database and NAND content, and its heap.
void FaceSystem::exit() { CFL_Exit(); }
