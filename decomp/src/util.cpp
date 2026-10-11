// Small utilities of the game: source/crc.cpp (crc.o), source/macaddress.cpp (macaddress.o) and
// source/utf.cpp (utf.o).
//
// Reconstructed by hand from decomp/raw/source/{crc,macaddress,utf}.cpp and the disassembly. Not compilable
// on its own.

// ---- crc.cpp -------------------------------------------------------------------------------------------

static u32 *s_table;                    // 0x0038E9C0 built on first use (operator new, 1 KB)

// zlib's CRC-32 (polynomial 0xEDB88320, initial and final complement). The game hashes every BXML name
// with it, and checks its network blocks (datastreamer.cpp).
u32 generateCRC(const void *data, u32 size)        // 0x0023F53C
{
	if (s_table == nullptr) {
		s_table = new u32[256];
		for (u32 n = 0; n < 256; n++) {
			u32 c = n;
			for (int k = 0; k < 8; k++)
				c = c & 1 ? c >> 1 ^ 0xEDB88320 : c >> 1;
			s_table[n] = c;
		}
	}
	u32 crc = 0xFFFFFFFF;
	for (const u8 *p = (const u8 *)data; size--; p++)
		crc = s_table[(*p ^ crc) & 0xFF] ^ crc >> 8;
	return ~crc;
}

u32 generateCRC(const char *string) { return generateCRC(string, strlen(string)); }   // 0x0023BDF0

// ---- macaddress.cpp ------------------------------------------------------------------------------------

struct MacAddress {
	u8 bytes[6];
	char text[18];                      // "xx:xx:xx:xx:xx:xx" (generateAddressHR: human readable)
};

static MacAddress s_zero;               // 0x0052E5B2 00:00:00:00:00:00 (the "no address" of the local play)

// 0x0021BAEC
void MacAddress::generateAddressHR()
{
	char *p = text;
	for (int i = 0; i < 6; i++) {
		sprintf(p, "%02x", bytes[i]);
		p += 2;
		if (i < 5)
			*p++ = ':';
	}
}

// ---- utf.cpp -------------------------------------------------------------------------------------------

// The Unicode Consortium's reference converter (ConvertUTF.c: ConvertUTF8toUTF16 0x0023AF24,
// ConvertUTF16toUTF8 0x0023B380, with its tables at 0x00356843 / 0x00356944 / 0x0035683C), under the
// names convertUTF8toUTF16 / convertUTF16toUTF8; results 0 ok, 1 source exhausted, 2 target exhausted,
// 3 illegal; `strict` = 0 turns lone surrogates into U+FFFD.

// 0x0023B164: the number of characters of a UTF-8 string (continuation bytes skipped).
int UTF8_Length(const char *s)
{
	int n = 0;
	while (*s) {
		n++;
		if ((*s & 0xC0) == 0xC0)
			for (s++; (*s & 0xC0) == 0x80; s++) {}
		else
			s++;
	}
	return n;
}
