// source/sys/textdata.cpp (textdata.o): the texts of the game, "text/<language>.bxml": a <strings> node
// of <string key="..." text="..." color="r g b a" typeface="..." line_spacing char_spacing scaleH scaleV
// tab_width/> (docs/formats.md). A text is found by its key, with its style; what a string does not give
// comes from the string "DEFAULT".
//
// Reconstructed by hand from decomp/raw/source/sys/textdata.cpp and the disassembly. Not compilable on its
// own. Attribute names are looked up by their CRC-32 (BXML), each computed once (guarded statics
// 0x0038EC48..0x0038EC94).

struct TextStyle {                      // 9 words
	const char *text;
	u32 color;                          // bit 0: a colour was given; then r << 8, g << 16, b << 24
	u8 alpha;
	const char *typeface;
	float lineSpacing, charSpacing;
	float scaleH, scaleV;
	int tabWidth;
};

static bool s_fromCard;                 // 0x0038EC40 the texts came from the developers' override (below)
static BXML::Node *s_strings;           // 0x0038EC44 <strings>
static TextStyle s_default;             // 0x005CEDDC the string "DEFAULT"'s style

bool TextData::hasStrings() { return s_strings != nullptr; }   // 0x00117AC0
const TextStyle *TextData::getDefaultStyle() { return &s_default; }  // 0x0023B374

// 0x00132424: a <string>'s fields; a number may be an integer or a float.
static TextStyle getFieldFromNode(const BXML::Node *node)
{
	TextStyle style = s_default;
	style.text = nullptr;
	if (auto *a = node->findAttribute(crc("text")))
		style.text = a->string();
	if (auto *a = node->findAttribute(crc("color"))) {
		const u32 *rgba = a->ints();
		style.color = 1 | (rgba[0] & 0xFF) << 8 | (rgba[1] & 0xFF) << 16 | rgba[2] << 24;
		style.alpha = rgba[3];
	} else {
		style.color = s_default.color & ~0xFF;     // the default colour, "not given"
		style.alpha = s_default.alpha;
	}
	if (auto *a = node->findAttribute(crc("typeface")))
		style.typeface = a->string();
	auto number = [](const BXML::Attribute *a, float fallback) {
		return a == nullptr ? fallback : a->type() == BXML::FLOAT ? a->floats()[0] : (float)a->ints()[0];
	};
	style.lineSpacing = number(node->findAttribute(crc("line_spacing")), s_default.lineSpacing);
	style.charSpacing = number(node->findAttribute(crc("char_spacing")), s_default.charSpacing);
	style.scaleH = number(node->findAttribute(crc("scaleH")), s_default.scaleH);
	style.scaleV = number(node->findAttribute(crc("scaleV")), s_default.scaleV);
	if (auto *a = node->findAttribute(crc("tab_width")))
		style.tabWidth = a->ints()[0];
	return style;
}

// 0x0023B220: the text of a key and its style. A missing key gives the default style and, as text, the key
// itself (keyIfMissing) or "".
TextStyle TextData::find(const char *key, bool keyIfMissing)
{
	const BXML::Node *node = s_strings->findNodeWithAttribute(crc("string"), crc("key"), key, strlen(key));
	if (node != nullptr)
		return getFieldFromNode(node);
	TextStyle style = s_default;
	style.text = keyIfMissing ? key : "";
	return style;
}

// 0x002F4A54: loads "text/<language>.bxml" ("EU_English"...). Before the RomFS's file, the developers' override: when the save data has a file
// "data:/text/<language>.bxml", that many bytes are read from "sdmc:/text/<language>.bxml" on the SD card
// and used instead. The retail save has no such file: the override never happens.
void TextData::loadStrings(const char *language)
{
	ScopedHeap heap(System::getSysHeap());
	char path[128];
	strncpy(path, "text/", 128);
	strncat(path, language, 128);
	strncat(path, ".bxml", 128);
	BXML bxml;
	bool mounted = SaveData::open(false);
	if (mounted) {
		u32 size = SaveData::getSize(path);                   // data:/text/<language>.bxml
		void *data = alloc(size);
		char card[128];
		SDCard::getPath(card, path);                         // "sdmc:/" + path
		nn::fs::FileInputStream file;
		s32 read = 0;
		if (file.TryInitialize(card).IsSuccess()) {
			file.TryRead(&read, data, size);
			file.Finalize();
			SaveData::close();
			if (read > 0) {
				bxml.initFromData(data);
				s_fromCard = true;
			}
		}
	}
	if (!s_fromCard)
		bxml.load(path);
	s_strings = bxml.findNode("strings");
	if (mounted)
		SaveData::close();
	s_default = find("DEFAULT", true);
}
