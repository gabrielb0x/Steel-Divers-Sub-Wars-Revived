// source/sys/binxml.cpp (binxml.o): the reader of the game's binary XML (.bxml: levels, statistics, texts;
// format in docs/formats.md, tools/bxml.py). The file is used in place: its offsets are turned into
// pointers once (adjustPointerOffsets), then nodes and attributes are read directly.
//
// Reconstructed by hand from decomp/raw/source/sys/binxml.cpp and the disassembly. Not compilable on its
// own.

struct Attribute {                      // 0x18 bytes
	u32 type;                           // 1 name, 2 bytes, 3 string, 4 s16[], 5 s32[], 7 f32[]; 100: empty
	u32 hash;                           // CRC-32 (zlib's) of its name
	char *name;
	u32 nameLength;                     // computed while relocating
	void *data;
	u32 size;                           // bytes
};

struct Node {                           // 0x18 bytes
	Node *parent, *sibling, *child;
	int attributeCount;                 // the first attribute is the node's name
	Attribute *attributes;
	int capacity;                       // DynamicNode
};

struct BXMLHeader { u32 magic; u32 version; Node *root; };   // "BXML" ("LMXB" on disk), 1

// ---- loading -------------------------------------------------------------------------------------------

// 0x0024FA4C: a .bxml of the RomFS (Resource: read once, shared; `copy` for a private copy), relocated once.
void BXML::load(const char *name, bool copy)
{
	ResourceData *r = Resource::getResource(name, 0x80);
	header = (BXMLHeader *)Resource::getData(r, copy, 0x80);
	if (!r->relocated) {
		header->root = (Node *)((u8 *)header + (u32)header->root);
		adjustPointerOffsets();
		r->relocated = true;
	}
}

// 0x0010BE6C: data already in memory (TextData's SD card override).
void BXML::initFromData(void *data)
{
	header = (BXMLHeader *)data;
	header->root = (Node *)((u8 *)header + (u32)header->root);
	adjustPointerOffsets();
}

// 0x001166CC: every node, depth first: parent, sibling, child and attribute array become pointers, as do
// each attribute's name and data; the names' lengths are measured.
void BXML::adjustPointerOffsets()
{
	u8 *base = (u8 *)header;
	auto fix = [base](auto *&pointer) { if (pointer) pointer = (decltype(pointer))(base + (u32)pointer); };
	Node *node = header->root;
	while (node != nullptr) {
		if (node->attributes) {
			fix(node->attributes);
			for (int i = 0; i < node->attributeCount; i++) {
				Attribute &a = node->attributes[i];
				fix(a.name);
				fix(a.data);
				if (a.name)
					a.nameLength = strlen(a.name);
			}
		}
		fix(node->parent);
		fix(node->sibling);
		if (node->child) {
			fix(node->child);
			node = node->child;
			continue;
		}
		// next: the sibling, or the sibling of the nearest ancestor that has one (already relocated)
		Node *up = node;
		node = node->sibling;
		while (node == nullptr) {
			up = up->parent;
			if (up == nullptr)
				return;
			node = up->sibling;
		}
	}
}

// 0x002DCC28: an empty document with a root node (for the files the game writes).
void BXML::init(const char *rootName)
{
	header = new BXMLHeader{0x42584D4C, 1, new DynamicNode(rootName, 0)};
}

Node *BXML::getRootNode() { return header ? header->root : nullptr; }   // 0x0024FA3C

// 0x0024F870: a node by its path "a.b.c" (each part at most 31 characters), searching `depth` levels under
// each part.
Node *BXML::findNode(const char *path, int depth)
{
	Node *node = getRootNode();
	if (node == nullptr || path == nullptr)
		return nullptr;
	for (const char *dot; (dot = strchr(path, '.')) != nullptr; path = dot + 1) {
		char part[32];
		strncpy(part, path, min(dot - path, 31));
		part[min(dot - path, 31)] = 0;
		if ((node = node->findNode(part, depth)) == nullptr)
			return nullptr;
	}
	return node->findNodeWithAttribute(path, nullptr, nullptr, 0, depth);
}

// ---- nodes ---------------------------------------------------------------------------------------------

// 0x00235618
const char *Node::getName()
{
	return attributeCount > 0 && attributes && attributes[0].nameLength > 0 ? attributes[0].name : nullptr;
}

Node *Node::getParent() { return parent; }               // 0x002DCC20
Node *Node::getSibling() { return sibling; }             // 0x002DCB90
Node *Node::getChild() { return child; }                 // 0x002DCC10
Attribute *Node::getAttribute(int i) { return &attributes[i]; }   // 0x0023567C

// 0x0023BBC0: this node or one of its descendants (`depth` levels) named `name` and, if `attribute` is
// given, whose attribute of that name has the value `value` (its first `length` bytes).
Node *Node::findNodeWithAttribute(const char *name, const char *attribute, const char *value, u32 length, int depth)
{
	if (getName() && strcmp(getName(), name) == 0) {
		if (attribute == nullptr)
			return this;
		for (int i = 1; i < attributeCount; i++) {
			if (strcmp(attributes[i].name, attribute) == 0) {
				if (memcmp(value, attributes[i].data, length) == 0)                    // 0x00242D34
					return this;
				break;
			}
		}
	}
	if (depth != 0)
		for (Node *c = child; c != nullptr; c = c->sibling)
			if (Node *found = c->findNodeWithAttribute(name, attribute, value, length, depth - 1))
				return found;
	return nullptr;
}

// 0x00139168: the same by the CRC-32 of the names (TextData: "string", "key").
Node *Node::findNodeWithAttribute(u32 nameHash, u32 attributeHash, const char *value, u32 length, int depth)
{
	if (attributeCount > 0 && attributes && attributes[0].nameLength > 0 && attributes[0].hash == nameHash) {
		if (attributeHash == 0)
			return this;
		for (int i = 1; i < attributeCount; i++) {
			if (attributes[i].hash == attributeHash) {
				if (memcmp(value, attributes[i].data, length) == 0)
					return this;
				break;
			}
		}
	}
	if (depth != 0)
		for (Node *c = child; c != nullptr; c = c->sibling)
			if (Node *found = c->findNodeWithAttribute(nameHash, attributeHash, value, length, depth - 1))
				return found;
	return nullptr;
}

// 0x0023BD00: the same path search as BXML::findNode, from this node.
Node *Node::findNode(const char *path, int depth);

// 0x0024F9C4: a direct child by name.
Node *Node::findChild(const char *name)
{
	for (Node *c = child; c != nullptr; c = c->sibling)
		if (strcmp(c->getName(), name) == 0)
			return c;
	return nullptr;
}

// 0x00233BF8 / 0x0024F954: an attribute (not the name) by the CRC-32 of its name, or by its name.
Attribute *Node::findAttribute(u32 hash)
{
	for (int i = 1; i < attributeCount; i++)
		if (attributes[i].hash == hash)
			return &attributes[i];
	return nullptr;
}

Attribute *Node::findAttribute(const char *name)
{
	for (int i = 1; i < attributeCount; i++)
		if (strcmp(attributes[i].name, name) == 0)
			return &attributes[i];
	return nullptr;
}

// 0x001DA6C4: appended after the last child.
bool Node::addChild(Node *node)
{
	if (node == nullptr)
		return false;
	if (child == nullptr) {
		child = node;
	} else {
		Node *last = child;
		while (last->sibling)
			last = last->sibling;
		last->sibling = node;
	}
	node->parent = this;
	return true;
}

// 0x002DCBA0
bool Node::removeChild(Node *node)
{
	if (child == nullptr || node == nullptr)
		return false;
	if (child == node) {
		child = node->sibling;
	} else {
		Node *previous = child;
		while (previous->sibling && previous->sibling != node)
			previous = previous->sibling;
		if (previous->sibling != node)
			return false;
		previous->sibling = node->sibling;
	}
	node->parent = node->sibling = nullptr;
	return true;
}

// ---- nodes and attributes the game builds (synced properties, saved files) ------------------------------

// 0x001E2714: a node with room for `attributes` attributes after its name (the global allocator).
DynamicNode::DynamicNode(const char *name, int attributes)
{
	parent = sibling = child = nullptr;
	attributeCount = 0;
	capacity = attributes + 1;
	this->attributes = (Attribute *)alloc(capacity * sizeof(Attribute));
	u32 length = strlen(name);
	char *copy = nullptr;
	u32 hash = 0;
	if (length > 0) {
		copy = (char *)alloc(length + 1);
		strcpy(copy, name);
		hash = generateCRC(copy);
	}
	this->attributes[attributeCount++] = {100, hash, copy, length, nullptr, 0};
}

// 0x001DA694: no check against the capacity.
void DynamicNode::addAttribute(const Attribute &a) { attributes[attributeCount++] = a; }

// A DynamicAttribute (0x78 bytes) holds its name (32 bytes at +0x18) and its data (64 bytes at +0x38).
// 0x00218D3C / 0x0012368C: empty; 0x0024A30C: named; 0x001E1F00 and 0x002DCB10: a copy.
DynamicAttribute::DynamicAttribute(const char *name)
{
	type = 100;
	this->name = nameBuffer;
	data = dataBuffer;
	size = 0;
	setName(name);
}

// 0x001DF4FC
void DynamicAttribute::setName(const char *name)
{
	strcpy(this->name, name);
	nameLength = strlen(name);
	hash = generateCRC(name);
}

// 0x00123648, 0x0023F21C, 0x00123668, 0x0024A2B4, 0x0023F1D0: the value and its type.
void DynamicAttribute::setByteData(const void *v, u32 n) { size = n; memcpy(data, v, size); type = 2; }
void DynamicAttribute::setCharData(const void *v, u32 n) { size = n; memcpy(data, v, size); type = 3; }
void DynamicAttribute::setShortData(const void *v, u32 n) { size = n * 2; memcpy(data, v, size); type = 4; }
void DynamicAttribute::setIntData(const void *v, u32 n) { size = n * 4; memcpy(data, v, size); type = 5; }
void DynamicAttribute::setFloatData(const void *v, u32 n) { size = n * 4; memcpy(data, v, size); type = 7; }

// 0x002DCC84, 0x002DCCA4, 0x002DCCC4: an attribute of a file keeps its size, only its value changes.
void Attribute::setIntData(const void *v) { memcpy(data, v, size); type = 5; }
void Attribute::setCharData(const void *v) { memcpy(data, v, size); type = 3; }
void Attribute::setShortData(const void *v) { memcpy(data, v, size); type = 4; }

// 0x00249ED4: runs into a memclr of its data.
void Attribute::clearData() { memset(data, 0, size); }
