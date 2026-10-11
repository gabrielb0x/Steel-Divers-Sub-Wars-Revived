// source/amx/amxxml.cpp (amxxml.o): the scripts' BXML natives (natives_XML, amx_XMLInit 0x001711C0): read the
// game's .bxml files (stats, rewards, crews...) and build small ones. Documents, nodes and attributes are
// native pointers in cells (binxml.cpp).
//
// Reconstructed by hand from decomp/raw/source/amx/amxxml.cpp and the disassembly. Not compilable on its own.

#define SELF AMXLoader *self = AMXLoader::getCurrentLoader()
static void str(AMXLoader *self, char *dst, cell addr) { dst[0] = 0; self->getString(dst, addr); }

// 0x0032BCB8: xmlLoad(name[], &document): a new BXML (operator new, never freed) loaded from the RomFS
// (Resource: shared, relocated once); true when loaded.
static cell n_xmlLoad(AMX *, const cell *p)
{
	SELF;
	char name[384];
	str(self, name, p[1]);
	BXML *bxml = new BXML();
	bxml->load(name, false);
	if (bxml->header == nullptr)
		return 0;
	*self->getAddr(p[2], 0) = (cell)bxml;
	return 1;
}

// Thunks into binxml.cpp (8 bytes each): the root (0x0024FA34), a node's parent, child, sibling
// (0x002DCC18, 0x002DCC08, 0x002DCB88), adding and removing a child (0x001DA6BC, 0x002DCB98).
static cell n_xmlGetRootNode(AMX *, const cell *p) { return (cell)((BXML *)p[1])->getRootNode(); }
static cell n_xmlNodeParent(AMX *, const cell *p) { return (cell)((Node *)p[1])->parent; }
static cell n_xmlNodeChild(AMX *, const cell *p) { return (cell)((Node *)p[1])->child; }
static cell n_xmlNodeSibling(AMX *, const cell *p) { return (cell)((Node *)p[1])->sibling; }
static cell n_xmlNodeAdd(AMX *, const cell *p) { return ((Node *)p[1])->addChild((Node *)p[2]); }
static cell n_xmlNodeRemove(AMX *, const cell *p) { return ((Node *)p[1])->removeChild((Node *)p[2]); }

static cell n_xmlNodeNumChildren(AMX *, const cell *p) { int n = 0; for (Node *c = ((Node *)p[1])->child; c; c = c->sibling) n++; return n; }   // 0x0032C284
static cell n_xmlNodeFind(AMX *, const cell *p) { SELF; char path[384]; str(self, path, p[2]); return (cell)((Node *)p[1])->findNode(path, 4); }        // 0x0032BD5C
static cell n_xmlNodeGetName(AMX *, const cell *p) { SELF; self->setString(((Node *)p[1])->getName(), p[2]); return 1; }                          // 0x0032BF5C
static cell n_xmlDumpNode(AMX *, const cell *p) { if (p[1]) BXMLPrinter::print((Node *)p[1], 0); return 1; }                                       // 0x0032B8E0 (to the log)

// xmlNodeGet*(node, attribute[], out): true when the node has the attribute.
static Attribute *attr(AMXLoader *self, const cell *p) { char n[384]; str(self, n, p[2]); return ((Node *)p[1])->findAttribute(n); }

// 0x0032BE78: a char, short or int attribute (other types: false).
static cell n_xmlNodeGetInt(AMX *, const cell *p)
{
	SELF;
	Attribute *a = attr(self, p);
	if (a == nullptr)
		return 0;
	cell *out = self->getAddr(p[3], 0);
	switch (a->type & 0xFF) {
	case 3: *out = *(s8 *)a->data; return 1;
	case 4: *out = *(s16 *)a->data; return 1;
	case 5: *out = *(s32 *)a->data; return 1;
	}
	return 0;
}
static cell n_xmlNodeGetReal(AMX *, const cell *p) { SELF; Attribute *a = attr(self, p); if (a) *self->getAddr(p[3], 0) = *(cell *)a->data; return a != nullptr; }   // 0x0032C104 (the first word, whatever its type)
static cell n_xmlNodeGetString(AMX *, const cell *p) { SELF; Attribute *a = attr(self, p); if (a) self->setString((const char *)a->data, p[3]); return a != nullptr; }   // 0x0032C18C
static cell n_xmlNodeGetVector(AMX *, const cell *p) { SELF; Attribute *a = attr(self, p); if (a) { VEC3 v = a->asVector(); memcpy(self->getAddr(p[3], 0), &v, 12); } return a != nullptr; }   // 0x0032C200
static cell n_xmlNodeGetRGB(AMX *, const cell *p) { SELF; Attribute *a = attr(self, p); if (a) { u32 c = a->asColor(); cell *o = self->getAddr(p[3], 0); o[0] = c & 0xFF; o[1] = c >> 8 & 0xFF; o[2] = c >> 16 & 0xFF; } return a != nullptr; }   // 0x0032BF94

// 0x0032BDA4: xmlNodeGetArray(node, attribute[], out[], max): at most max words of it.
static cell n_xmlNodeGetArray(AMX *, const cell *p)
{
	SELF;
	Attribute *a = attr(self, p);
	if (a == nullptr)
		return 0;
	int n = min((int)(a->size / 4), p[4]);
	memcpy(self->getAddr(p[3], 0), a->data, n * 4);
	return 1;
}

// 0x0032C030: xmlNodeGetRanged(node, attribute[], &out): a value "min max" gives a random float between
// them (System::random(0x7FFFFFFF) / 2^31); a single value is itself (a 4-byte attribute).
static cell n_xmlNodeGetRanged(AMX *, const cell *p)
{
	SELF;
	Attribute *a = attr(self, p);
	if (a == nullptr)
		return 0;
	f32 *out = (f32 *)self->getAddr(p[3], 0);
	const f32 *v = (const f32 *)a->data;
	if (a->size == 4)
		*out = v[0];
	else
		*out = v[0] + System::random(0x7FFFFFFF) * 4.656613e-10f * (v[1] - v[0]);
	return 1;
}

// 0x0032C2B8 / 0x0032C35C: an attribute's value replaced, its type and size kept.
static cell n_xmlNodeSetInt(AMX *, const cell *p)
{
	SELF;
	Attribute *a = attr(self, p);
	if (a == nullptr)
		return 0;
	cell v = p[3];
	switch (a->type & 0xFF) {
	case 3: { s8 c = v; a->setCharData(&c); break; }
	case 4: { s16 s = v; a->setShortData(&s); break; }
	case 5: a->setIntData(&v); break;
	}
	return 1;
}
static cell n_xmlNodeSetString(AMX *, const cell *p) { SELF; Attribute *a = attr(self, p); if (a) { char s[384]; str(self, s, p[3]); a->setCharData(s); } return a != nullptr; }

// Building: 0x0032BC64 xmlDynNodeCreate(name[]): a node with room for 16 attributes; xmlDynNodeAddAttr*(node,
// name[], value): a new DynamicAttribute (0x78 bytes) int (0x0032B908), float (0x0032BA4C), string
// (0x0032BAE0), 3 ints (RGB, 0x0032B99C) or 3 floats (vector, 0x0032BBA0). True when the node exists.
static cell n_xmlDynNodeCreate(AMX *, const cell *p) { SELF; char n[384]; str(self, n, p[1]); return (cell)new DynamicNode(n, 16); }
template <typename Set> static cell addAttr(const cell *p, Set set)
{
	SELF;
	char n[384];
	str(self, n, p[2]);
	DynamicNode *node = (DynamicNode *)p[1];
	if (node == nullptr)
		return 0;
	DynamicAttribute *a = new DynamicAttribute();
	a->setName(n);
	set(self, a, p[3]);
	node->addAttribute(*a);
	return 1;
}
static cell n_xmlDynNodeAddAttrInt(AMX *, const cell *p) { return addAttr(p, [](AMXLoader *, DynamicAttribute *a, cell v) { a->setIntData(&v, 1); }); }
static cell n_xmlDynNodeAddAttrReal(AMX *, const cell *p) { return addAttr(p, [](AMXLoader *, DynamicAttribute *a, cell v) { a->setFloatData(&v, 1); }); }
static cell n_xmlDynNodeAddAttrString(AMX *, const cell *p) { return addAttr(p, [](AMXLoader *s, DynamicAttribute *a, cell v) { char t[384]; str(s, t, v); a->setCharData(t, strlen(t)); }); }
static cell n_xmlDynNodeAddAttrRGB(AMX *, const cell *p) { return addAttr(p, [](AMXLoader *s, DynamicAttribute *a, cell v) { a->setIntData(s->getAddr(v, 0), 3); }); }
static cell n_xmlDynNodeAddAttrVector(AMX *, const cell *p) { return addAttr(p, [](AMXLoader *s, DynamicAttribute *a, cell v) { a->setFloatData(s->getAddr(v, 0), 3); }); }
