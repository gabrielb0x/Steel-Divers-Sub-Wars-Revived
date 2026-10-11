// source/amx/amxutils.cpp (amxutils.o) and source/amx/amxprofiler.cpp (amxprofiler.o), and where the rest
// of the Pawn runtime comes from.
//
// Reconstructed by hand from decomp/raw/source/amx/{amxutils,amxprofiler}.cpp and the disassembly. Not
// compilable on its own.
//
// The Pawn runtime itself is CompuPhase's (Pawn 3.3, sources in build/ref/compuphase-pawn @ 6d82fa4,
// `make pawncc`): source/amx/amx.cpp is amx.c (amx_Init, amx_Exec, amx_Register, amx_FindPublic,
// amx_Push*, amx_GetAddr, amx_GetString/SetString...), amxcore.cpp is amxcore.c (numargs, getarg, setarg,
// heapspace, funcidx, the properties, min/max/clamp, random, tolower/toupper, swapchars), amxstring.cpp is
// amxstring.c (strlen, strpack, strcat, strfind, strformat, valstr, uuencode, urlencode...), and
// amxcons.cpp is amxcons.c (print, printf and the console natives, writing nowhere in the retail build).
// They are not rewritten here; amxdbg.cpp is empty (only its static initialiser).

// ---- amxutils.cpp --------------------------------------------------------------------------------------

static char *s_scratch[3];              // 0x0038DDD0 1 KB each (the system allocator)

// 0x00101380
void initAmxScratchBuffers()
{
	for (char *&b : s_scratch)
		b = (char *)alloc(0x400);
}

char *getAmxScratchBuffer1() { return s_scratch[0]; }   // 0x001DB240
char *getAmxScratchBuffer2() { return s_scratch[1]; }   // 0x001DB250

// 0x001DB260: the texts' placeholders. A text like "#2/#1/#0" (texts: card_datestamp) gets, for each "#N",
// the N-th of the native's string arguments (from `first` on; "##" is a "#"). Each placeholder becomes a
// "%s" formatted with that string (snprintf, 0x0023B1C4) through the third scratch buffer. A placeholder past
// the arguments stops there (a log: "source/amx/amxutils.cpp").
char *keystring_sprintf(char *out, int size, const char *text, const cell *params, int first, AMXLoader *script)
{
	strncpy(out, text, size - 1);
	out[size - 1] = 0;
	char *work = s_scratch[2];
	strcpy(work, out);
	int available = params[0] / sizeof(cell) - first + 1;
	for (char *p = work; *p; ) {
		if (p[0] != '#') {
			p++;
			continue;
		}
		if (p[1] == '#') {                  // "##"
			strcpy(p, p + 1);
			p++;
			continue;
		}
		if (!isdigit(p[1])) {
			p++;
			continue;
		}
		int n = atoi(p + 1);                // 0x0016E3D0
		p[0] = '%';
		p[1] = 's';
		if (n >= available)
			return out;
		if (n > 9) {                        // the other digits go
			char *q = p + 2;
			while (isdigit(*q))
				q++;
			strcpy(p + 2, q);
		}
		char value[384];
		script->getString(value, params[first + n]);      // vtable +0x30
		snprintf(out, size, work, value);
		strcpy(work, out);
		p += strlen(value);
	}
	return out;
}

// ---- amxprofiler.cpp: named counters of the scripts' profiling (sysProfileBegin/End) -------------------

struct Profile {                        // 0x1C bytes, 40 of them (*0x0038E924)
	u8 pad;
	char name[16];                      // +0x01
	bool running;                       // +0x11
	u32 calls;                          // +0x18
};
static u32 s_profileCount;              // 0x0038E920
static Profile *s_profiles;             // 0x0038E924

void AMXProfiler::resetProfiles() { s_profileCount = 0; }   // 0x00101BF0

// 0x001790F0: counts a call of a section (by its first 16 characters).
void AMXProfiler::beginProfile(const char *name)
{
	if (s_profileCount >= 40)
		return;
	u32 i = 0;
	for (; i < s_profileCount; i++) {
		if (strncmp(name, s_profiles[i].name, 16) == 0 && !s_profiles[i].running) {   // 0x0023A7FC
			s_profiles[i].running = true;
			s_profiles[i].calls++;
			return;
		}
	}
	s_profiles[i].running = true;
	strncpy(s_profiles[i].name, name, 16);
	s_profiles[s_profileCount].calls = 1;
	s_profileCount++;
}

// 0x00179068
void AMXProfiler::endProfile(const char *name)
{
	for (u32 i = 0; i < s_profileCount; i++) {
		if (strncmp(name, s_profiles[i].name, 16) == 0 && s_profiles[i].running) {
			s_profiles[i].running = false;
			return;
		}
	}
}
