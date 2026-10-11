// source/sys/exception.cpp (exception.o): the developers' crash handler. On an exception the game stops
// every other thread and prints a backtrace of the faulting thread's stack, each return address named with
// the linker's symbol listing, the very file the RomFS still ships as romfs:/map ("%x %d %s %s": address,
// size, function, object). In the retail build nothing loads that listing any more (the pointer is never
// set) and the prints are compiled out: the handler does nothing visible.
//
// Reconstructed by hand from decomp/raw/source/sys/exception.cpp and the disassembly. Not compilable on its
// own. Strings: "Exception at 0x%08x", " 0x%08x : %s() in %s".

static bool s_handled;                  // 0x0038E9F8 the first exception only
static const char *s_map;               // 0x0038E9FC the symbol listing's text: never set

// 0x00107994 (System's start-up): the handler runs on its own stack (0x00593C68).
void exceptionRegisterHandler() { nn::os::ARM::SetUserExceptionHandler(myExceptionHandler, (void *)0x00593C68); }

// 0x0011067C: the thread's priority raised to the highest (svc 0x0C, SetThreadPriority), then the backtrace.
static void myExceptionHandler(nn::os::ExceptionInfo *, nn::os::ExceptionContext *context)
{
	if (s_handled)
		return;
	s_handled = true;
	nn::os::Thread::ChangeCurrentPriority(0);                // ConvertLibraryToSvcPriority(0), svc 0x0C
	showException(context->pc, context->sp);                   // +0x3C, +0x34 ("Exception at 0x%08x")
}

// 0x0011AD2C: walks the stack (to the thread's top, or 16 KB) for words that are return addresses: just
// after an ARM BL/BLX/BX-register or a Thumb BL/BLX pair; each is looked up in the listing, from the
// innermost frame up to nnMain() (50 frames at most); then the faulting address itself.
static void showException(void *pc, u32 sp)
{
	if (s_map == nullptr)
		return;
	u32 top = stackTopOf(sp);                // the ManagedThread holding sp, else sp + 0x4000 (below 0x10000000)
	for (u32 *p = (u32 *)top - 1; p >= (u32 *)sp; p--) {
		if (!isReturnAddress(*p))
			continue;
		u32 address, size;
		char name[256], object[256];
		for (const char *line = s_map; *line; line = nextLine(line)) {
			if (sscanf(line, "%x %d %s %s", &address, &size, name, object) == 4   // 0x00237B14
			    && address <= *p && *p < address + size) {
				// " 0x%08x : %s() in %s"
				break;
			}
		}
	}
}
