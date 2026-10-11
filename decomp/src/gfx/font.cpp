// source/gfx/font.cpp (font.o) and source/gfx/gfxallocations.cpp (gfxallocations.o): the fonts of the
// texts, and the counters of the graphics memory allocations.
//
// Reconstructed by hand from decomp/raw/source/gfx/{font,gfxallocations}.cpp and the disassembly. Not
// compilable on its own.

// ---- font.cpp ------------------------------------------------------------------------------------------

struct LoadedFont {                     // 0x24 bytes (0x004DBC5C)
	char name[32];
	nw::font::ResFont *font;
};
static LoadedFont s_fonts[];            // no bound checked
static u32 s_count;                     // 0x0038E38C
static LoadedFont *s_default;           // 0x0038E388

// 0x0010C4E8: "fonts/<name>.bcfnt", once (by name), in the device heap: "Loading Font %s".
void Font::load(const char *name)
{
	for (u32 i = 0; i < s_count; i++)
		if (strcmp(s_fonts[i].name, name) == 0)
			return;
	ScopedHeap heap(System::getDeviceHeap());
	char path[128];
	sprintf(path, "fonts/%s.bcfnt", name);
	ResourceData *r = Resource::getResource(path, 0x80);
	void *drawBuffer = alloc(nw::font::ResFont::GetDrawBufferSize(Resource::getData(r, false, 0x80)));
	nw::font::ResFont *font = new nw::font::ResFont();
	s_fonts[s_count].font = font;
	font->SetResource(Resource::getData(r, false, 0x80));
	font->SetDrawBuffer(drawBuffer);
	strcpy(s_fonts[s_count].name, name);
	s_count++;
}

// 0x00254100: every <font name="..."> of a list (main.cpp: "fonts/title-fonts.bxml" and
// "fonts/main-fonts.bxml"; the native sysLoadFonts).
void Font::loadFonts(const char *list)
{
	BXML bxml;
	bxml.load(list, false);
	for (BXML::Node *n = bxml.findNode("font", 4); n != nullptr; n = n->getSibling())
		load((const char *)n->findAttribute("name")->data);
}

// 0x0013927C: by name, else the default one ("Font not loaded: %s").
LoadedFont *Font::getFont(const char *name)
{
	for (u32 i = 0; i < s_count; i++)
		if (strcmp(s_fonts[i].name, name) == 0)
			return &s_fonts[i];
	return s_default;
}

void Font::setDefaultFont(const char *name) { s_default = getFont(name); }   // 0x002DECBC

// ---- gfxallocations.cpp --------------------------------------------------------------------------------

// Per memory area (0x10000 FCRAM, 0x20000 VRAM A, 0x30000 VRAM B) and per purpose of nngx's allocator
// (0x100..0x105, then "other"): bytes and counts. 0x34 bytes per area.
struct GFXAllocations {
	struct { u32 bytes[6]; u32 counts[6]; u32 total; } area[3];
};

GFXAllocations::GFXAllocations() { reset(); }                 // 0x0017F7A8
void GFXAllocations::reset() { memset(this, 0, sizeof *this); }   // 0x0010963C

// 0x0011C0B0. "Other" purposes are index 6, one past bytes[]: they land in counts[0] (and counts[6] in
// `total`'s place... as written: bytes[6] is counts[0], counts[6] is `total`).
void GFXAllocations::addAllocation(u32 memory, u32 purpose, u32 size)
{
	int a = memory == 0x20000 ? 1 : memory == 0x30000 ? 2 : 0;
	int k = purpose >= 0x100 && purpose <= 0x105 ? purpose - 0x100 : 6;
	area[a].bytes[k] += size;
	area[a].total++;
	area[a].counts[k]++;
}

// 0x0011C168: "Usage for %s", "%s: memory usage %.1fkB, allocations %u" (the logs are gone).
void GFXAllocations::printUsageStatistics() {}
