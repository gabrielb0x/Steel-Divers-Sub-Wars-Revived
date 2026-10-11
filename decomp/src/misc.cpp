// Small modules: source/memblock.cpp, source/property.cpp, source/waitscreen.cpp, source/texture.cpp.
//
// Reconstructed by hand from decomp/raw/source/{memblock,property,waitscreen,texture}.cpp and the
// disassembly. Not compilable on its own.

// ---- memblock.cpp: blocks of memory kept for reuse within a mode ---------------------------------------

struct MemBlock {                       // 0x14 bytes
	void *data;
	u32 size, alignment;
	bool attached;                      // +0x0C in use
	MemBlock *next;                     // +0x10
};

static MemBlock *s_blocks;              // 0x0038EAC8
static u32 s_attached, s_count;         // 0x0038EACC, 0x0038EAD0

void MemBlock::resetStock() { s_blocks = nullptr; s_attached = s_count = 0; }  // 0x00105004 (main.cpp, per mode)

// 0x002F0628: a new block (allocAligned), at the head of the stock.
MemBlock::MemBlock(u32 size, u32 alignment)
	: data(allocAligned(size, alignment)), size(size), alignment(alignment), next(s_blocks)
{
	s_blocks = this;
	s_count++;
}

// 0x002F05DC: a free block of this size whose alignment is enough.
MemBlock *MemBlock::findStock(u32 size, u32 alignment)
{
	for (MemBlock *b = s_blocks; b != nullptr; b = b->next)
		if (b->size == size && alignment <= b->alignment && !b->attached)
			return b;
	return nullptr;
}

void MemBlock::attach() { attached = true; s_attached++; }    // 0x002F059C
void MemBlock::release() { attached = false; s_attached--; }  // 0x002F05BC

// ---- property.cpp: setting an actor's dynamic property (a BXML DynamicAttribute) ----------------------

void DynamicProperty::setInt(int value) { attribute->setIntData(&value, 1); }             // 0x0023B870
void DynamicProperty::setFloat(float value) { attribute->setFloatData(&value, 1); }       // 0x001E1F78
void DynamicProperty::setVector3(const VEC3 &v) { attribute->setFloatData(&v, 3); }       // 0x0023B838
void DynamicProperty::setString(const char *s)                                            // 0x0023F1F4
{
	attribute->size = strlen(s) + 1;
	memcpy(attribute->data, s, attribute->size);
	attribute->type = 3;
}

// ---- waitscreen.cpp: what turns while the game waits for the network (Connection::wait*) --------------

static bool s_showing;                  // 0x0038E590

void WaitScreen::init() { s_showing = false; }   // 0x00101BDC

// 0x0021AAFC: one frame: the loading icon (shown the first time), the HOME lock icon, the power button,
// then both screens cleared to black with the icons (the top one for each eye), and two vertical blanks.
void WaitScreen::render()
{
	if (!s_showing) {
		Icons::showLoading();
		s_showing = true;
	}
	Renderer *top = Renderer::getRenderer(1), *bottom = Renderer::getRenderer(2);
	u32 black = 0xFF000000;
	System::checkPowerButton();
	Icons::showHomeLock();
	Icons::update();
	Graphics::setViewport(0);
	Graphics::clear(&black, true, true);
	Icons::drawStereo(top, 1);
	Graphics::transferBuffer(0);
	Graphics::clear(&black, true, true);
	Icons::drawStereo(top, 2);
	Graphics::transferBuffer(1);
	Graphics::setViewport(1);
	Graphics::clear(&black, true, true);
	Icons::draw(bottom);
	Graphics::transferBuffer(2);
	Graphics::stopDraw();
	Graphics::flip(1);
	Graphics::runDraw();
	Graphics::waitVBlank();
	Graphics::waitVBlank();
}

// 0x0021AAD4
void WaitScreen::end()
{
	if (s_showing) {
		Icons::hideLoading();
		s_showing = false;
	}
}

// ---- texture.cpp: "textures/<name>.bin" (docs/formats.md: a 5-byte header, then the texels) -----------

// 0x0024D120: the header kept, the texels copied to VRAM (Graphics::allocate, DMA).
Texture::Texture(const char *name)
{
	char path[128];
	strncpy(path, "textures/", 128);
	strncat(path, name, 128);
	strncat(path, ".bin", 128);
	MemStream file = Resource::getFileMem(path, false, 0x80);
	file.read(header, 5);                       // width (u16), height (u16), format (u8)
	size = file.size - 5;
	vram = Graphics::allocate(0x20000, 0x101, 0, size);
	nngxAddVramDmaCommand(file.data + 5, vram, size);
}
