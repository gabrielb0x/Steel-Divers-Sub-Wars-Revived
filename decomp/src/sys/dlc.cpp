// source/sys/dlc.cpp (dlc.o): the shop and the add-on contents ("DLC"): the full version ("premium",
// "enlist" in the code) and the five historical submarines, sold on the eShop.
//
// Reconstructed by hand from decomp/raw/source/sys/dlc.cpp, amxsys.cpp and the disassembly. Not compilable
// on its own. See docs/premium.md for what the game does with it, and mods/premium for the patches.
//
// NsubShop wraps the SDK's purchase library (nn::ec): an EcApplet for the purchase screens, a Session and a
// Server for the eShop, a ContentSetCatalog of the items for sale and a DataTitle for what the console owns.
// The add-on contents form one title, 0004008C000D7E00 (the game is 00040000000D7E00), whose contents are
// numbered: content n is item n. The game only asks two questions of it:
//   checkPaidForFullVer()  content 91 owned: the full version
//   checkCondition(n)      content n owned (1..5: submarines 19..23, bxml/pscope_ply19..23 <mount_dlc_arc>)
// Left out: _setItemInfo (2024 bytes) and _getContentSetList (976 bytes), which fill the catalog's item
// table (name, description, price, release date, size, "new" flag, from the metadata reader) for the shop
// scripts, and ReportNnError (9716 bytes), a switch from SDK result codes to error dialogs.

// ---- NsubShop (one instance, 0x005920B8; getNsubShop() 0x00235644) --------------------------------------
class NsubShop {
	void **vtable;                  // +0x00 (0x00376B10)
	bool busy;                      // +0x04 an asynchronous request runs (sysDLCWaitThread waits for 0)
	nn::os::Thread thread;          // +0x08 NsubThread: calls exec() until busy is cleared
	int request;                    // +0x10 1 content set list, 2 balance, 3 delete an item, 4 server time
	nn::ec::CTR::ResultError lastResult;   // +0x14 checkLastResult()
	nn::ec::CTR::EcApplet applet;   // +0x1C
	nn::ec::CTR::Session session;   // +0x20
	nn::ec::CTR::Server server;     // +0x24
	u32 eshopId[2];                 // +0x28 {unique id 0xD7E, 0x2F0002}: the application, for the eShop
	u32 dataTitle[2];               // +0x30 {unique id 0xD7E, 0x2F0000}: the add-on content title
	nn::ec::CTR::MetaDataReader metaData;  // +0x40 the content info archive (names, prices...), +0x40/+0x44 mounted
	nn::ec::CTR::ContentSetCatalog *catalog;   // +0x90 createCatalog(): 1 MB of main memory at +0x94,
	void *catalogMemory, *filterMemory;        // +0x94, +0x98 and 4 KB for the filter
	int catalogOffset;              // +0x9C
	ItemInfo items[5];              // +0xA0 0x300 bytes each: what the shop scripts show (sysDLCGetItem*)
	u32 owned[4];                   // +0xFA0 bitmap of the owned contents 0..127 (updateCondition)
	u8 balance[0x20], price[...];   // +0xFB0, +0xFD0 the account's balance, as a price string
	int deleteIndex;                // +0x1050 deleteItemAsync()
	void *contentArchiveMemory;     // +0x1054 mountContentArchive()
	bool contentArchiveMounted;     // +0x1058
	nn::fs::DateTime serverTime;    // +0x1060 getServerTimeAsync()
	char filter[4][0x40];           // +0x1068 the catalog filter: "==", "string", "ITEM_TYPE", the item type
	int filterMode;                 // +0x11A8 sysDLCSetFilterModeEnlist / ...Submarine: "ENLIST" or the subs
};

// 0x002F1528: sysDLCInit (mode_title, at every start of the title screen).
void NsubShop::initializeEc()
{
	nn::ec::CTR::Initialize(...);
	nn::ec::CTR::Session::Invalidate();
	u32 uniqueId = System::getUniqueId();         // 0xD7C JP, 0xD7D US, 0xD7E EU
	eshopId[0] = uniqueId;   eshopId[1] = 0x2F0002;
	dataTitle[0] = uniqueId; dataTitle[1] = 0x2F0000;
}

// 0x0013A098: what the console owns. Called by sysDLCUpdateCondition (title screen, lobby, hangar...) and
// before reading a property file with <mount_dlc_arc> (Actor::readProperties).
void NsubShop::updateCondition()
{
	owned[0] = owned[1] = owned[2] = owned[3] = 0;
	nn::ec::CTR::DataTitle title;
	Result result = title.Initialize(dataTitle);
	if (result.IsFailure()) {
		ReportEcErrorVerbose(result);
		return;
	}
	int count = 0;
	result = title.GetContentCount(&count);                    // 0x0014358C
	if (result.IsFailure()) {
		ReportEcErrorVerbose(result);
		return;
	}
	ContentInfo *list = new ContentInfo[count];                // 0x18 bytes each
	result = title.GetContentInfoList(list, &count, 0);        // 0x00143520
	if (result.IsFailure()) {
		ReportEcErrorVerbose(result);
		return;
	}
	for (int i = 0; i < count; i++) {
		// flags (+0x10): bit 0 the rights (bought), bit 1 the content is on the console (downloaded)
		if (list[i].isOnDevice() && list[i].isOwned()) {
			owned[list[i].index / 32] |= 1 << (list[i].index % 32);
		}
	}
}

// 0x0013A06C: content n owned. sysDLCCheckCondition (0x0013A054) loads the singleton and runs into it.
bool NsubShop::checkCondition(u32 n)
{
	return owned[n / 32] & (1 << (n % 32));
}

// 0x002F1EF4: the full version, content 91 (bit 27 of the third word). sysDLCCheckPaidForFullVer
// (0x002F1EE4) runs into it too. Every mode script has isFullVersion() { return sysDLCCheckPaidForFullVer(); }.
bool NsubShop::checkPaidForFullVer()
{
	return owned[2] & 0x08000000;
}

// 0x0013A220: mounts the archive of content n as "content:" (getContentArchiveName, 0x002F1F04), so that
// Resource::setArchiveName("content:") makes the next model come from it (model_mutable_dlc).
bool NsubShop::mountContentArchive(u32 n)
{
	size_t size = 0;
	Result result = nn::fs::GetAddOnContentRequiredMemorySize(&size, dataTitle, n);
	if (result.IsFailure()) {
		ReportEcErrorVerbose(result);
		return false;
	}
	Allocator *allocator = System::getMainMemAllocator();
	contentArchiveMemory = allocator->AllocAligned(size, 4);
	result = nn::fs::MountAddOnContent("content:", dataTitle, n, contentArchiveMemory, size);
	if (result.IsFailure()) {
		allocator->Free(contentArchiveMemory);
		ReportEcErrorVerbose(result);                          // may show the error applet
		return false;
	}
	contentArchiveMounted = true;
	return true;
}

// 0x0013A384
bool NsubShop::unmountContentArchive()
{
	if (!contentArchiveMounted) {
		return false;
	}
	if (nn::fs::Unmount("content:").IsFailure()) {
		ReportEcErrorVerbose(...);
		return false;
	}
	System::getMainMemAllocator()->Free(contentArchiveMemory);
	contentArchiveMounted = false;
	return true;
}

// ---- the eShop session (the shop scripts: mode_shop for the submarines, mode_sale for the full version) ----

// 0x002F1944: sysDLCValidateSession
bool NsubShop::validateSession()
{
	if (session.Validate() >= 0) {
		return true;
	}
	return _initializeSession();
}

// 0x002F1D4C: the purchase applet opens the session with a per-region eShop identifier (a numeric string,
// table 0x003556D0, JP/US/EU from bxml/settings.bxml), then the Server object talks to the eShop.
bool NsubShop::_initializeSession()
{
	int region = !strcmp(System::getRegion(), "JP") ? 0 : !strcmp(System::getRegion(), "US") ? 1 :
	             !strcmp(System::getRegion(), "EU") ? 2 : -1;
	Result result = applet.RequestInitializeSession(&session, eshopId, s_eshopIds[region], dataTitle, true);
	if (result.IsFailure()) {
		ReportNnError(result);
	} else if (server.Initialize(session, eshopId).IsSuccess()) {
		return true;
	}
	return ReportEcErrorVerbose(result);
}

// 0x002F1974: sysDLCInvalidateSession
void NsubShop::invalidateSession() { nn::ec::CTR::Session::Invalidate(); }

// 0x002F1650 / 0x002F16BC: sysDLCCreateCatalog / sysDLCDestroyCatalog: 1 MB for the catalog, 4 KB for the filter.
void NsubShop::createCatalog()
{
	Allocator *allocator = System::getMainMemAllocator();
	catalogMemory = allocator->AllocAligned(0x100000, 4);
	filterMemory = allocator->AllocAligned(0x1000, 4);
	if (catalogMemory && filterMemory) {
		catalog = new nn::ec::CTR::ContentSetCatalog(session, catalogMemory, 0x100000);
	}
}

// 0x002F1FA4 / 0x00186260: sysDLCInitializeMetaDataReader / ...Finalize: the content info of the add-on
// title (names, descriptions, prices, icons of the items) is mounted raw.
bool NsubShop::initializeMetaDataReader() { return metaData.Initialize(dataTitle).IsSuccess(); }

// ---- the requests that wait for the eShop: a thread (NsubThread::callFromThread, 0x00177074) calls exec()
//      every 10 ms while busy; the scripts loop on sysDLCWaitThread() then read sysDLCCheckLastResult(). ----

// 0x002F1F14 getContentSetListAsync (request 1), 0x002F18B4 getBalanceAsync (2), 0x002F1824 deleteItemAsync (3),
// 0x002F1E60 getServerTimeAsync (4): set request, start the thread (priority 0x10, 4 KB stack), busy = true.

// 0x002F1FF0
void NsubShop::exec()
{
	switch (request) {
	case 1: _getContentSetList(); break;       // the catalog filtered on ITEM_TYPE (ENLIST or the subs)
	case 2: _getBalance(); break;              // Server::GetBalance + ConvertPrice into a string
	case 3: _deleteItem(deleteIndex); break;   // deletes the contents of an item from the console
	case 4: lastResult = server.GetDateTime(&serverTime); break;
	}
	busy = false;
}

// 0x002F17EC: sysDLCCheckLastResult
bool NsubShop::checkLastResult()
{
	if (lastResult.IsFailure()) {
		ReportNnError(lastResult);
		ReportEcErrorVerbose(lastResult);
		return false;
	}
	return true;
}

// ---- buying: the purchase applet of the system shows the price, takes the money and downloads ----

// 0x002F15EC: sysDLCPurchaseItem(item)
bool NsubShop::purchaseItem(int item)
{
	Result result = applet.RequestPurchaseContentSet(dataTitle, &items[item]);
	if (result.IsFailure()) {
		lastResult = result;
		return ReportEcErrorVerbose(result);
	}
	return true;
}

// 0x002F1744: sysDLCRedownloadItem(item): an item already bought (the contents of its content set)
bool NsubShop::redownloadItem(int item)
{
	u16 contents[64];
	int count = catalog->Get(item).GetContentIndexList(contents);
	Result result = applet.RequestDownloadContents(dataTitle, contents, count);
	if (result.IsFailure()) {
		lastResult = result;
		return ReportEcErrorVerbose(result);
	}
	return true;
}

// 0x002F0AF8: sysDLCAddBalance: the applet to add money to the account
bool NsubShop::addBalance() { return applet.RequestManageBalance().IsSuccess() || ReportEcErrorVerbose(...); }

// 0x0022F9B8: logs "[DLC::ReportEcErrorVerbose] Error: Level = %d, Summary = %d, Module = %d, Description = %d"
// (log removed in the retail build) and, for the errors meant for the player, shows the error applet
// (System::showErrEULA). Returns true when nothing was shown.

// ---- NsubAcConnection (0x005920A8, getNsubAcConnection 0x001DA710): the internet connection of the shop ----
//   +0x04 state: 0 idle, 1 connecting, 2 done;  +0x08 the event of nn::ac::ConnectAsync

// 0x00182F64: sysDLCAcSetupConnect
void NsubAcConnection::setupConnect()
{
	if (state == 0) {
		nn::ac::CTR::Initialize();
	}
}

// 0x00182E44: sysDLCAcTryConnect: true when the attempt is over (successful or not). On failure the
// connection is closed and an error code shown (System::showErrEULA).
bool NsubAcConnection::tryConnect()
{
	Result result;
	int errorCode;
	bool over = _connectAsync(&result, &errorCode);           // 0x00182FE4
	if (over && result.IsFailure()) {
		disconnect();
		if (errorCode) {
			System::showErrEULA(errorCode);
		}
	}
	return over;
}

// 0x00182F38: sysDLCAcIsConnected: 1 connected, 0 not yet, -1 the attempt failed (the scripts start over).
int NsubAcConnection::isConnected()
{
	if (nn::ac::CTR::IsConnected()) {
		return 1;
	}
	if (state == 2) {
		state = 0;
		return -1;
	}
	return 0;
}

// 0x00182E08: sysDLCAcDisconnect
void NsubAcConnection::disconnect()
{
	if (nn::ac::CTR::IsConnected()) {
		nn::ac::CTR::Close();
	}
	if (nn::ac::CTR::IsInitialized()) {
		nn::ac::CTR::Finalize();
	}
	state = 0;
}
