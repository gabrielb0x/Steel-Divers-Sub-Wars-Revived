// source/game/collision.cpp (collision.o): the collision shapes of the actors (<collshape type="..."/> in an
// actor's XML, up to 2 per actor, game/actor.cpp) and the exact tests between them. CollisionScene
// (collisionscene.cpp) pairs the actors, checks the shapes' bounding spheres, then calls a.intersect(b).
//
// Reconstructed by hand from decomp/raw/source/game/collision.cpp and the disassembly. Not compilable on its
// own. The segment tests follow Ericson's Real-Time Collision Detection (ClosestPtSegmentSegment, the
// point-in-triangle test by barycentric coordinates).
//
// Shapes used by Sub Wars' data: capsule (the subs, torpedoes...), hmap (the scenery), sphere, box, bounds
// (one). "edges", "points", "skeleton" and "level" are leftovers of the Steel Diver engine (the 2D side view):
// no actor of the game uses them, and their slips below never show.
//
// Double dispatch: a.intersect(b, r) calls b.intersect<KindOfA>(a, r). The result names the two actors
// (actorA = a's, actorB = b's); an implementation that puts b first swaps it (CollResult::swap toggles
// `swapped`, which processCollisions undoes). The normal points from the second shape to the first: away
// from the other actor.

struct CollResult {                     // 0x38 bytes
	f32 depth;                          // +0x00 distance minus the radii (< 0: they overlap); a smaller one wins
	VEC3 point;                         // +0x04
	VEC3 normal;                        // +0x10
	VEC3 otherVelocity;                 // +0x1C (collisionscene.cpp)
	Actor *actorA, *actorB;             // +0x28, +0x2C
	bool swapped;                       // +0x30
	int part;                           // +0x34 the bone (skeleton) or point number + 1 (points) that touched
};

class CollShape {                       // vtable 0x00376BA8
public:
	VEC3 offset;                        // +0x04 from the actor's position ("offset" is the capsule's own)
	VEC3 size;                          // +0x10 "size" (box: full size), or the radius on each axis
	f32 boundingRadius;                 // +0x1C what CollisionScene tests first
	char name[32];                      // +0x20 "name"
	char type[32];                      // +0x40 "type"
	CollShape *nextInStock;             // +0x60
	bool movable;                       // +0x64 "movable": hmap in the actor's frame (else world coordinates)
	bool relative;                      // +0x65 offset relative to the actor's position (always true)
	bool isStatic;                      // +0x66 edges, level
	bool enabled;                       // +0x67 in use by an actor (false: free in the stock, reusable)

	virtual void draw(Actor *actor);                                   // +0x00
	virtual bool intersect(CollShape *other, CollResult *r);           // +0x04
	virtual bool intersectPoint(const VEC3 &p, CollResult *r);         // +0x08
	virtual bool intersectSphere(CollShape *s, CollResult *r);         // +0x0C
	virtual bool intersectCapsule(CollShape *s, CollResult *r);        // +0x10
	virtual bool intersectEdges(CollShape *s, CollResult *r);          // +0x14
	                                                                   // +0x18 eliminated by armlink (points)
	virtual bool intersectSkeleton(CollShape *s, CollResult *r);       // +0x1C
	virtual bool intersectBounds(CollShape *s, CollResult *r);         // +0x20
	virtual bool intersectBox(CollShape *s, CollResult *r);            // +0x24
	virtual bool intersectHeightMap(CollShape *s, CollResult *r);      // +0x28
	virtual void clipLine(const VEC3 &from, const VEC3 &to, const VEC3 &dir, f32 &t);   // +0x2C
	virtual f32 getHeightAt(f32 x, f32 z, VEC3 *normal);               // +0x30
	virtual void setProperty(const BXML::Attribute *a);                // +0x34
	virtual void read(const BXML::Node *node);                         // +0x38
};

// 0x00110F78: a depth of 0, so that only overlaps are kept.
void CollResult::reset() { depth = 0; swapped = false; }

// 0x00110F2C
void CollResult::swap()
{
	std::swap(actorA, actorB);
	normal = -normal;
	swapped = !swapped;
}

// ---- the stock ---------------------------------------------------------------------------------------------
// Every shape ever made is in a list; a shape no actor uses any more (enabled = false) is reused by the next
// create() of the same type. The list is emptied (not freed: the level's heap goes) when a mode starts.

static CollShape *s_stock;              // 0x0038E288

void CollShape::resetStock() { s_stock = nullptr; }   // 0x001062D8

// 0x0022F914: every shape is linked into the stock, even the temporary spheres the skeleton tests build on
// the stack (below): after such a test the stock's head is a dead stack frame. Only skeletons do it, and no
// actor of the game has one.
CollShape::CollShape()
{
	offset = size = VEC3(0, 0, 0);
	boundingRadius = 0;
	name[0] = type[0] = 0;
	relative = true;
	isStatic = enabled = false;
	nextInStock = s_stock;
	s_stock = this;
}

// 0x0013A6BC: the shape of a <collshape type="..." .../> node, a free one of that type when there is one.
CollShape *CollShape::create(const BXML::Node *node)
{
	const char *kind = node->findAttribute(crc("type"))->string();
	CollShape *shape = nullptr;
	for (CollShape *s = s_stock; s != nullptr; s = s->nextInStock)
		if (!s->enabled && strcmp(s->type, kind) == 0) {
			shape = s;
			break;
		}
	if (shape == nullptr) {
		if (strcmp(kind, "edges") == 0)         shape = new CollShapeEdges();      // 0x88, static
		else if (strcmp(kind, "capsule") == 0)  shape = new CollShapeCapsule();    // 0x80
		else if (strcmp(kind, "points") == 0)   shape = new CollShapePoints();     // 0xE4
		else if (strcmp(kind, "sphere") == 0)   shape = new CollShapeSphere();     // 0x68
		else if (strcmp(kind, "level") == 0)    shape = new CollShapeLevel();      // 0x68, static
		else if (strcmp(kind, "skeleton") == 0) shape = new CollShapeSkeleton();   // 0x290
		else if (strcmp(kind, "bounds") == 0)   shape = new CollShapeBounds();     // 0x68
		else if (strcmp(kind, "box") == 0)      shape = new CollShapeBox();        // 0x68
		else if (strcmp(kind, "hmap") == 0)     shape = new CollShapeHeightMap();  // 0xAC
		strncpy(shape->type, kind, 32);     // an unknown type: a null shape, and a crash here
	}
	shape->enabled = true;
	shape->read(node);
	return shape;
}

// 0x002F6A84: every attribute but the first ("type") goes to setProperty.
void CollShape::read(const BXML::Node *node)
{
	for (int i = 1; i < node->attributeCount; i++)
		setProperty(node->getAttribute(i));
}

// 0x002186DC. The attribute readers (0x0021867C float, 0x00217224 vector, 0x00235650 int, 0x00308050 bool)
// accept an integer or a float attribute.
void CollShape::setProperty(const BXML::Attribute *a)
{
	if (strcmp(a->name, "name") == 0)
		strncpy(name, a->string(), 32);
	else if (strcmp(a->name, "type") == 0)
		strncpy(type, a->string(), 32);
	else if (strcmp(a->name, "size") == 0) {
		size = a->vec3();
		boundingRadius = length(size);
	} else if (strcmp(a->name, "radius") == 0)
		size.x = size.y = size.z = boundingRadius = a->number();
	else if (strcmp(a->name, "movable") == 0)
		movable = a->boolean();
}

// 0x002F69F0: the debug view, a green box of the shape's size 50 units above the actor (the shapes' draws:
// green primitives, Renderer::addPrimitive colour 0xFF00FF00; edges, bounds and hmap draw nothing).
void CollShape::draw(Actor *actor)
{
	VEC3 at = VEC3(actor->positionPtr) + VEC3(0, 0, 50);
	Renderer::getRenderer(0)->addPrimitive(0, at, size, 0xFF00FF00);
}

// The defaults: no hit, no ground (0x002F4FF8 returns height 0, not "nothing": World::getHeightAt then sees
// ground at 0 under every active actor of the asked types that has no hmap).
bool CollShape::intersect(CollShape *, CollResult *) { return false; }           // 0x002F6AE8
f32 CollShape::getHeightAt(f32, f32, VEC3 *) { return 0; }                         // 0x002F4FF8
void CollShape::clipLine(const VEC3 &, const VEC3 &, const VEC3 &, f32 &) {}      // 0x002F6AE4
bool CollShape::intersectBox(CollShape *, CollResult *) { return false; }        // 0x002F5004
bool CollShape::intersectEdges(CollShape *, CollResult *) { return false; }      // 0x002F500C
bool CollShape::intersectPoint(const VEC3 &, CollResult *) { return false; }     // 0x002F5014
bool CollShape::intersectBounds(CollShape *, CollResult *) { return false; }     // 0x002F501C
bool CollShape::intersectSphere(CollShape *, CollResult *) { return false; }     // 0x002F5024
bool CollShape::intersectCapsule(CollShape *, CollResult *) { return false; }    // 0x002F502C
bool CollShape::intersectSkeleton(CollShape *, CollResult *) { return false; }   // 0x002F5034
bool CollShape::intersectHeightMap(CollShape *, CollResult *) { return false; }  // 0x002F503C

// The centre of a shape: its offset, plus the position of its actor (the result's actorA or actorB).
static VEC3 centre(const CollShape *s, const Actor *actor)
{
	return s->relative ? s->offset + VEC3(actor->positionPtr) : s->offset;     // Actor +0x6C
}

// Keep a hit only if it is deeper than the result's.
static bool keep(CollResult *r, f32 depth, const VEC3 &point, const VEC3 &normal)
{
	if (!(depth < r->depth))
		return false;
	r->depth = depth;
	r->point = point;
	r->normal = normal;
	r->part = 0;
	return true;
}

// ---- spheres --------------------------------------------------------------------------------------------

// 0x002170FC: a on actorA, b on actorB. The point should be on b's surface (b's centre + n * b's radius):
// it takes a's radius, the same thing for two spheres of one size. Concentric spheres divide by zero.
bool CollShape::intersectSphereSphere(CollShape *a, CollShape *b, CollResult *r)
{
	VEC3 ca = centre(a, r->actorA), cb = centre(b, r->actorB);
	f32 reach = a->boundingRadius + b->boundingRadius;
	VEC3 d = ca - cb;
	if (!(dot(d, d) < reach * reach))
		return false;
	VEC3 n = d / length(d);
	return keep(r, length(d) - reach, cb + n * a->boundingRadius, n);
}

// 0x002170A8, then 0x002170FC
bool CollShapeSphere::intersectSphere(CollShape *other, CollResult *r)
{
	r->swap();
	return intersectSphereSphere(this, other, r);
}

bool CollShapeSphere::intersect(CollShape *other, CollResult *r) { return other->intersectSphere(this, r); }  // 0x001801A8
bool CollShapeSphere::intersectPoint(const VEC3 &p, CollResult *r) { return intersectPointSphere(p, this, r); }  // 0x002F53B8

// 0x002F53C8: a point (of actorA's shape) in a sphere of actorB; the point is the hit, the normal goes from
// the sphere's centre to it.
bool CollShape::intersectPointSphere(const VEC3 &p, CollShape *sphere, CollResult *r)
{
	VEC3 d = p - centre(sphere, r->actorB);
	f32 radius = sphere->boundingRadius;
	if (!(dot(d, d) < radius * radius))
		return false;
	return keep(r, length(d) - radius, p, d / length(d));
}

// The spheres against boxes and bounds: the sphere is its actor's position (its offset is not used) with its
// radius.
bool CollShapeBox::intersectSphere(CollShape *s, CollResult *r)   // 0x0017A994
{
	return intersectSphereBox2(VEC3(r->actorA->positionPtr), s->boundingRadius, this, r);
}
bool CollShapeSphere::intersectBox(CollShape *box, CollResult *r)  // 0x0017FF20
{
	r->swap();
	return intersectSphereBox2(VEC3(r->actorA->positionPtr), boundingRadius, box, r);
}
bool CollShapeBounds::intersectSphere(CollShape *s, CollResult *r)  // 0x0017FAF4
{
	return intersectSphereBounds2(VEC3(r->actorA->positionPtr), s->boundingRadius, this, r);
}
bool CollShapeSphere::intersectBounds(CollShape *bounds, CollResult *r)  // 0x0017FFF4
{
	r->swap();
	return intersectSphereBounds2(VEC3(r->actorA->positionPtr), boundingRadius, bounds, r);
}

// 0x0017FFA0, 0x002F54A4, 0x002F612C, 0x00180074: the same pattern (swap, then the shared test).
bool CollShapeSphere::intersectEdges(CollShape *edges, CollResult *r) { r->swap(); return intersectSphereEdges(this, edges, r); }
bool CollShapeEdges::intersectSphere(CollShape *s, CollResult *r) { return intersectSphereEdges(s, this, r); }
bool CollShapeSphere::intersectSkeleton(CollShape *sk, CollResult *r) { r->swap(); return intersectSphereSkeleton(this, sk, r); }
bool CollShapeSphere::intersectHeightMap(CollShape *hmap, CollResult *r)
{
	r->swap();
	return ((CollShapeHeightMap *)hmap)->intersectSphere(VEC3(r->actorA->positionPtr), boundingRadius, r);
}

// 0x001800FC: a green box of the sphere's radius on the actor.
void CollShapeSphere::draw(Actor *actor);

// ---- capsules -------------------------------------------------------------------------------------------
// "length" between the two end centres, "width" = the radius, "offset" along the axis, "axis" (0..2, default
// 2) of the actor's matrix with its roll, "bulge" (default 1): the middle sphere's radius factor against the
// scenery.

class CollShapeCapsule : public CollShape {   // vtable 0x003766F0
	f32 length, lengthSq;               // +0x68, +0x6C
	f32 radius;                         // +0x70 "width"
	f32 axisOffset;                     // +0x74 "offset"
	int axis;                           // +0x78 "axis"
	f32 bulge;                          // +0x7C "bulge"
};

// 0x0018291C: the bounding size is |offset| + length / 2, without the radius.
void CollShapeCapsule::setProperty(const BXML::Attribute *a)
{
	if (strcmp(a->name, "length") == 0) {
		length = a->number();
		lengthSq = length * length;
	} else if (strcmp(a->name, "width") == 0) {
		radius = a->number();
		return;
	} else if (strcmp(a->name, "bulge") == 0) {
		bulge = a->number();
		return;
	} else if (strcmp(a->name, "offset") == 0) {
		axisOffset = a->number();
	} else if (strcmp(a->name, "axis") == 0) {
		axis = a->integer();
		return;
	} else {
		CollShape::setProperty(a);
		return;
	}
	f32 half = fabsf(axisOffset) + length * 0.5f;
	size = VEC3(half, half, half);
	boundingRadius = ::length(size);
}

// 0x00218A70: the two end centres, along the actor's axis (Actor::getAxisWithRollSim).
void CollShapeCapsule::calcEndpoints(Actor *actor, VEC3 *top, VEC3 *bottom)
{
	VEC3 at = VEC3(actor->positionPtr);
	VEC3 dir = actor->getAxisWithRollSim(axis);
	*top = at + dir * (axisOffset + length * 0.5f);
	*bottom = at + dir * (axisOffset - length * 0.5f);
}

bool CollShapeCapsule::intersect(CollShape *other, CollResult *r) { return other->intersectCapsule(this, r); }  // 0x00182DF0
bool CollShapeCapsule::intersectPoint(const VEC3 &p, CollResult *r) { return intersectPointCapsule(p, this, r); }  // 0x002F5C90

// 0x00216F08: the sphere's centre against the capsule's segment (ClosestPtSegmentSegment with a segment of
// one point, 0x001DF1BC, which returns the squared distance). The point is on the sphere's surface.
bool CollShape::intersectSphereCapsule(CollShape *sphere, CollShapeCapsule *capsule, CollResult *r)
{
	VEC3 top, bottom;
	capsule->calcEndpoints(r->actorB, &top, &bottom);
	VEC3 c = centre(sphere, r->actorA);
	f32 s, t;
	VEC3 c1, c2;
	f32 distSq = closestPtSegmentSegment(c, c, top, bottom, s, t, c1, c2);
	f32 reach = capsule->radius + sphere->boundingRadius;
	if (!(distSq < reach * reach))
		return false;
	VEC3 d = c - c2;
	if (d == VEC3(0, 0, 0))
		return false;
	VEC3 n = d / length(d);
	return keep(r, sqrtf(distSq) - reach, c - n * sphere->boundingRadius, n);
}

// 0x00216EB4, then 0x00216F08
bool CollShapeSphere::intersectCapsule(CollShape *capsule, CollResult *r)
{
	r->swap();
	return intersectSphereCapsule(this, (CollShapeCapsule *)capsule, r);
}

// 0x002F5FB8: segment against segment; the point is halfway between the two closest points. Segments that
// cross (closer than 0.001², compared on the float's bits) get the normal (0, 1, 0).
bool CollShape::intersectCapsuleCapsule(CollShapeCapsule *a, CollShapeCapsule *b, CollResult *r)
{
	VEC3 a0, a1, b0, b1;
	a->calcEndpoints(r->actorA, &a0, &a1);
	b->calcEndpoints(r->actorB, &b0, &b1);
	f32 s, t;
	VEC3 ca, cb;
	f32 distSq = closestPtSegmentSegment(a0, a1, b0, b1, s, t, ca, cb);
	f32 reach = a->radius + b->radius;
	if (!(distSq <= reach * reach))
		return false;
	VEC3 d = ca - cb;
	VEC3 n = dot(d, d) < 0.001f ? VEC3(0, 1, 0) : d / length(d);
	return keep(r, sqrtf(distSq) - reach, (ca + cb) * 0.5f, n);
}

// 0x002F5FA8, then 0x002F5FB8 (with this second).
bool CollShapeCapsule::intersectCapsule(CollShape *other, CollResult *r)
{
	return intersectCapsuleCapsule((CollShapeCapsule *)other, this, r);
}

// 0x002F5CA0: a point against a capsule. The parameter along the segment is the distance from the top end
// divided by the length, not the projection on the axis: a point beside the segment is compared with a
// point further down than its foot.
bool CollShape::intersectPointCapsule(const VEC3 &p, CollShapeCapsule *capsule, CollResult *r)
{
	VEC3 top, bottom;
	capsule->calcEndpoints(r->actorB, &top, &bottom);
	f32 t = clamp(length(p - top) / capsule->length, 0.0f, 1.0f);
	VEC3 q = top + (bottom - top) * t;
	VEC3 d = p - q;
	if (!(dot(d, d) < capsule->radius * capsule->radius))
		return false;
	return keep(r, length(d) - capsule->radius, p, d / length(d));
}

// Capsules against boxes and bounds: three spheres of the capsule's radius, at both ends and at the actor's
// position (0x0017A9C8, 0x00182AC4; 0x0017FB28, 0x00182C08).
bool CollShapeBox::intersectCapsule(CollShape *c, CollResult *r)
{
	CollShapeCapsule *capsule = (CollShapeCapsule *)c;
	VEC3 top, bottom;
	capsule->calcEndpoints(r->actorA, &top, &bottom);
	VEC3 at = VEC3(r->actorA->positionPtr);
	return intersectSphereBox2(top, capsule->radius, this, r) || intersectSphereBox2(bottom, capsule->radius, this, r)
		|| intersectSphereBox2(at, capsule->radius, this, r);
}
bool CollShapeCapsule::intersectBox(CollShape *box, CollResult *r)
{
	r->swap();
	VEC3 top, bottom;
	calcEndpoints(r->actorA, &top, &bottom);
	VEC3 at = VEC3(r->actorA->positionPtr);
	return intersectSphereBox2(top, radius, box, r) || intersectSphereBox2(bottom, radius, box, r)
		|| intersectSphereBox2(at, radius, box, r);
}
// CollShapeBounds::intersectCapsule and CollShapeCapsule::intersectBounds: the same with intersectSphereBounds2.

// 0x00182BB4, 0x002F586C, 0x002F630C, 0x00183894 / 0x002F6578: swap when needed, then the shared test.
bool CollShapeCapsule::intersectEdges(CollShape *e, CollResult *r) { r->swap(); return intersectCapsuleEdges(this, e, r); }
bool CollShapeEdges::intersectCapsule(CollShape *c, CollResult *r) { return intersectCapsuleEdges(c, this, r); }
bool CollShapeCapsule::intersectSkeleton(CollShape *sk, CollResult *r) { r->swap(); return intersectCapsuleSkeleton(this, sk, r); }
bool CollShapeHeightMap::intersectCapsule(CollShape *c, CollResult *r) { return intersectCapsuleHeightMap(c, this, r); }

// 0x002F65CC: a capsule against the scenery is five spheres: both ends, the actor's position with radius *
// bulge (a fatter hull in the middle), and the two points halfway between the position and the ends. Every
// sphere is tested; the deepest hit stays.
bool CollShape::intersectCapsuleHeightMap(CollShapeCapsule *capsule, CollShapeHeightMap *hmap, CollResult *r)
{
	VEC3 top, bottom;
	capsule->calcEndpoints(r->actorA, &top, &bottom);
	VEC3 at = VEC3(r->actorA->positionPtr);
	bool hit = hmap->intersectSphere(top, capsule->radius, r);
	hit |= hmap->intersectSphere(bottom, capsule->radius, r);
	hit |= hmap->intersectSphere(at, capsule->radius * capsule->bulge, r);
	hit |= hmap->intersectSphere((top + at) * 0.5f, capsule->radius, r);
	hit |= hmap->intersectSphere((bottom + at) * 0.5f, capsule->radius, r);
	return hit;
}

// 0x00182D08: the capsule as a green box. 0x001DF1BC closestPtSegmentSegment: Ericson's, unchanged.

// ---- boxes and bounds --------------------------------------------------------------------------------------

// 0x00218AFC: a sphere against a box of `size` centred on the box's actor (its offset is not used), in the
// actor's frame (Actor::getInverseMatrixSim); the closest point of the box and the normal go back to the
// world (the matrix, and its inverse transpose for the normal).
static bool intersectSphereBox2(VEC3 c, f32 radius, CollShape *box, CollResult *r)
{
	MTX34 world = r->actorB->getMatrixSim();
	c = r->actorB->getInverseMatrixSim() * c;
	VEC3 half = box->size * 0.5f;
	VEC3 q = clamp(c, -half, half);
	f32 distSq = dot(q - c, q - c);
	if (!(distSq <= radius * radius))
		return false;
	VEC3 n = c - q;
	if (dot(n, n) != 0)
		n = n / length(n);
	return keep(r, sqrtf(distSq) - radius, world * q, inverseTranspose(world) * n);
}

// 0x002174C0: the same against the oriented bounding boxes of every mesh of the actor's models (ModelSet
// +0x138; a shape whose bounding volume is an OBB, NW4C kind 0x10000001; the unit box -0.5..0.5 is placed by
// the OBB's centre, axes and size, through the skeleton's matrix for a skinned model). The first box hit
// returns. Only one actor of the game uses "bounds".
static bool intersectSphereBounds2(VEC3 c, f32 radius, CollShape *bounds, CollResult *r);

class CollShapeBox : public CollShape {};      // vtable 0x003763AC; 0x0017AB30 intersect: other->intersectBox(this)
class CollShapeBounds : public CollShape {};   // vtable 0x0037653C; 0x0017FBD8 intersect; 0x0017FBD4 draw: nothing
// 0x0017AA74 CollShapeBox::draw: a green box of the shape's size on the actor.

// ---- height maps (the scenery) -------------------------------------------------------------------------
// "hmaps/<file>.hmap" (docs/formats.md): a triangle mesh, indexed by a quadtree on X and Z built at load.

struct QuadTreeNode {                   // 0x1BC bytes
	int count;                          // +0x000
	int triangles[100];                 // +0x004
	VEC3 min, max;                      // +0x194 X and Z: the node's square; Y: the height of its triangles
	QuadTreeNode *children[4];          // +0x1AC
};

struct QuadTree {                       // CollShapeHeightMap +0x94
	QuadTreeNode *root;
	const u32 (*triangles)[3];          // +0x04
	const VEC3 *vertices;               // +0x08
	const VEC3 *normals;                // +0x0C
	int triangleCount;                  // +0x10
};

class CollShapeHeightMap : public CollShape {  // vtable 0x00376788
	VEC3 min, max;                      // +0x68 the file's bounding box
	int vertexCount, triangleCount;     // +0x80
	const u32 (*triangles)[3];          // +0x88
	const VEC3 *vertices;               // +0x8C
	const VEC3 *normals;                // +0x90
	QuadTree tree;                      // +0x94
};

// The outcode of a point against a node's square: 1 beyond max X, 2 below min X, 4 beyond max Z, 8 below
// min Z. (Its first test is written oddly but gives the same codes.)
static int outcode(const QuadTreeNode *n, f32 x, f32 z)
{
	int code = x > n->max.x ? 1 : x < n->min.x ? 2 : 0;
	return code | (z > n->max.z ? 4 : z < n->min.z ? 8 : 0);
}

// 0x0018356C
void CollShapeHeightMap::setProperty(const BXML::Attribute *a)
{
	if (strcmp(a->name, "file") == 0)
		load(a->string());
	else
		CollShape::setProperty(a);
}

// 0x001838A8: the file stays in the resource stock; the shape points into it. The bounding radius is the
// length of the farther corner. Every triangle is inserted in the tree.
void CollShapeHeightMap::load(const char *file)
{
	char path[128];
	strncpy(path, "hmaps/", 128);
	strncat(path, file, 128);
	strncat(path, ".hmap", 128);
	const u32 *data = (const u32 *)Resource::getFile(path);
	min = VEC3(data + 1);
	max = VEC3(data + 4);
	vertexCount = data[7];
	triangleCount = data[8];
	vertices = (const VEC3 *)(data + 9);
	triangles = (const u32 (*)[3])(vertices + vertexCount);
	normals = (const VEC3 *)(triangles + triangleCount);
	boundingRadius = std::max(::length(min), ::length(max));
	tree.root = new QuadTreeNode{0, {}, min, max};
	tree.triangles = triangles;
	tree.vertices = vertices;
	tree.normals = normals;
	tree.triangleCount = triangleCount;
	for (int i = 0; i < tree.triangleCount; i++)
		tree.checkInsert(tree.root, i, 0);
}

// 0x00213894: a triangle goes down to every node its X/Z outcodes do not rule out (a cheap test: a triangle
// beside a node's corner may land in it). A node splits at its second triangle, down to depth 5; a leaf at
// depth 5 holds 100 triangles, then drops the next ones (an assertion compiled out: line 1938 of
// "source/game/collision.cpp"). The children's height range starts empty (+10000 / -10000) and grows with
// their triangles.
void QuadTree::checkInsert(QuadTreeNode *node, int tri, int depth)
{
	const VEC3 &a = vertices[triangles[tri][0]], &b = vertices[triangles[tri][1]], &c = vertices[triangles[tri][2]];
	if (outcode(node, a.x, a.z) & outcode(node, b.x, b.z) & outcode(node, c.x, c.z))
		return;
	if (node->count != 0 && depth < 5) {
		if (node->children[0] == nullptr) {
			VEC3 mid = (node->min + node->max) * 0.5f;
			node->children[0] = new QuadTreeNode{0, {}, node->min, VEC3(mid.x, mid.y, mid.z)};
			node->children[1] = new QuadTreeNode{0, {}, VEC3(mid.x, 0, node->min.z), VEC3(node->max.x, 0, mid.z)};
			node->children[2] = new QuadTreeNode{0, {}, VEC3(node->min.x, 0, mid.z), VEC3(mid.x, 0, node->max.z)};
			node->children[3] = new QuadTreeNode{0, {}, mid, node->max};
			for (QuadTreeNode *child : node->children) {
				child->min.y = 10000;
				child->max.y = -10000;
				for (int i = 0; i < node->count; i++)
					checkInsert(child, node->triangles[i], depth + 1);
			}
		}
		for (QuadTreeNode *child : node->children)
			checkInsert(child, tri, depth + 1);
		return;
	}
	if (node->count < 100)                  // full: the triangle is lost, only the height range grows
		node->triangles[node->count++] = tri;
	for (const VEC3 *v : {&a, &b, &c}) {
		if (v->y < node->min.y)
			node->min.y = v->y;
		else
			node->max.y = std::max(node->max.y, v->y);
	}
}

// 0x002F25D8: the leaves whose square, widened by `radius`, holds (x, z); at most `max`.
int QuadTree::findNodes(QuadTreeNode *node, const VEC3 &p, f32 radius, QuadTreeNode **found, int max, int count)
{
	if (p.x < node->min.x - radius || p.x > node->max.x + radius || p.z < node->min.z - radius || p.z > node->max.z + radius)
		return count;
	if (node->children[0] == nullptr) {
		if (count < max)
			found[count++] = node;
		return count;
	}
	for (QuadTreeNode *child : node->children)
		count = findNodes(child, p, radius, found, max, count);
	return count;
}

// 0x00213D20: is p (on the triangle's plane) inside the triangle? Barycentric coordinates u, v >= 0 and
// u + v < 1 (that last one compared on the float's bits).
static bool inTriangle(const VEC3 &p, const VEC3 &a, const VEC3 &b, const VEC3 &c)
{
	VEC3 v0 = c - a, v1 = b - a, v2 = p - a;
	f32 d00 = dot(v0, v0), d11 = dot(v1, v1), d01 = dot(v0, v1), d02 = dot(v0, v2), d12 = dot(v1, v2);
	f32 inv = 1 / (d00 * d11 - d01 * d01);
	f32 u = (d11 * d02 - d01 * d12) * inv, v = (d00 * d12 - d01 * d02) * inv;
	return u >= 0 && v >= 0 && u + v < 1;
}

// 0x001835BC: the signed distance from a sphere's centre to the closest triangle under or over it, minus the
// radius (> 0: no contact; the radius itself when nothing is near). The centre must be inside the map's box
// (without the radius); 4 leaves at most are searched; a triangle counts when the centre's projection on its
// plane is inside it.
f32 CollShapeHeightMap::getDistanceQT(const VEC3 &c, f32 radius, VEC3 *point, VEC3 *normal)
{
	QuadTreeNode *root = tree.root;
	f32 best = radius * 2;
	if (c.y < root->min.y || c.y > root->max.y || c.x < root->min.x || c.x > root->max.x || c.z < root->min.z || c.z > root->max.z)
		return best - radius;
	QuadTreeNode *leaves[4];
	int count = tree.findNodes(root, c, radius, leaves, 4, 0);
	for (int i = 0; i < count; i++) {
		QuadTreeNode *leaf = leaves[i];
		if (c.y < leaf->min.y - radius || c.y > leaf->max.y + radius)
			continue;
		for (int k = 0; k < leaf->count; k++) {
			int tri = leaf->triangles[k];
			const VEC3 &n = normals[tri], &a = vertices[triangles[tri][0]];
			f32 d = dot(c - a, n);
			VEC3 q = c - n * d;
			if (inTriangle(q, a, vertices[triangles[tri][1]], vertices[triangles[tri][2]]) && fabsf(d) < fabsf(best)) {
				best = d;
				*point = q;
				*normal = n;
			}
		}
	}
	return best - radius;
}

// 0x00216D90: a sphere of actorA against the map of actorB (in that actor's frame when "movable").
bool CollShapeHeightMap::intersectSphere(const VEC3 &centre, f32 radius, CollResult *r)
{
	VEC3 c = movable ? r->actorB->getInverseMatrixSim() * centre : centre;
	VEC3 point, normal;
	f32 depth = getDistanceQT(c, radius, &point, &normal);
	if (!(depth < 0))
		return false;
	if (movable) {
		MTX34 world = r->actorB->getMatrixSim();
		point = world * point;
		normal = inverseTranspose(world) * normal;
	}
	return keep(r, depth, point, normal);
}

// 0x00183868: a sphere shape is its actor's position (and its radius, in s0).
bool CollShapeHeightMap::intersectSphere(CollShape *s, CollResult *r) { return intersectSphere(VEC3(r->actorA->positionPtr), s->boundingRadius, r); }
bool CollShapeHeightMap::intersectPoint(const VEC3 &p, CollResult *r) { return intersectSphere(p, 0, r); }   // 0x0018385C
bool CollShapeHeightMap::intersect(CollShape *other, CollResult *r) { return other->intersectHeightMap(this, r); }  // 0x00183BA0
void CollShapeHeightMap::draw(Actor *) {}   // 0x001838A4

// 0x002F2410 -> 0x002F241C: the highest triangle at (x, z) (world coordinates, even for a movable map), from
// -100000; `normal` gets its normal. In a split node the first child that has ground answers.
f32 CollShapeHeightMap::getHeightAt(f32 x, f32 z, VEC3 *normal) { return tree.getMaxHeightAt(tree.root, x, z, normal); }

f32 QuadTree::getMaxHeightAt(QuadTreeNode *node, f32 x, f32 z, VEC3 *normal)
{
	f32 best = -100000;
	if (outcode(node, x, z) != 0)
		return best;
	if (node->children[0] != nullptr) {
		for (QuadTreeNode *child : node->children) {
			f32 h = getMaxHeightAt(child, x, z, normal);
			if (h > best)
				return h;
		}
		return best;
	}
	for (int k = 0; k < node->count; k++) {
		int tri = node->triangles[k];
		const VEC3 &n = normals[tri], &a = vertices[triangles[tri][0]];
		f32 y = (n.x * x + n.z * z - dot(n, a)) / -n.y;       // the plane's height at (x, z)
		if (y > best && inTriangle(VEC3(x, y, z), a, vertices[triangles[tri][1]], vertices[triangles[tri][2]])) {
			best = y;
			if (normal != nullptr)
				*normal = n;
		}
	}
	return best;
}

// 0x00183B70 -> 0x002F2190: the segment from -> to, of direction dir, against the triangles facing it
// (dot(n, dir) < 0): t is lowered to the first hit in [0, t] (World::clipLine, the scripts' worldClipLine).
// The tree's nodes are culled with the segment's ends' outcodes only.
void CollShapeHeightMap::clipLine(const VEC3 &from, const VEC3 &to, const VEC3 &dir, f32 &t) { tree.clipLineNormal(tree.root, from, to, dir, t, nullptr); }

void QuadTree::clipLineNormal(QuadTreeNode *node, const VEC3 &from, const VEC3 &to, const VEC3 &dir, f32 &t, VEC3 *normal)
{
	if (outcode(node, from.x, from.z) & outcode(node, to.x, to.z))
		return;
	if (node->children[0] != nullptr) {
		for (QuadTreeNode *child : node->children)
			clipLineNormal(child, from, to, dir, t, normal);
		return;
	}
	for (int k = 0; k < node->count; k++) {
		int tri = node->triangles[k];
		const VEC3 &n = normals[tri], &a = vertices[triangles[tri][0]];
		f32 facing = dot(n, dir);
		if (!(facing < 0))
			continue;
		f32 hit = -(dot(n, from) - dot(n, a)) / facing;
		if (hit >= 0 && hit <= t && inTriangle(from + dir * hit, a, vertices[triangles[tri][1]], vertices[triangles[tri][2]])) {
			t = hit;
			if (normal != nullptr)
				*normal = n;
		}
	}
}

// ---- level (Steel Diver's playfield, unused) --------------------------------------------------------------
// "width": the half width; the half height is fixed at 500. A wall under the level actor's height - 500
// with the normal (0, -1, 0).

class CollShapeLevel : public CollShape {};    // vtable 0x00376490

// 0x0017E188
void CollShapeLevel::setProperty(const BXML::Attribute *a)
{
	if (strcmp(a->name, "width") != 0) {
		CollShape::setProperty(a);
		return;
	}
	size = VEC3(a->number(), 500, 0);
	boundingRadius = ::length(size);
}

bool CollShapeLevel::intersect(CollShape *, CollResult *) { return false; }   // 0x0017E414: a level starts nothing

// 0x0017E200: a point inside the level's rectangle (X, Y) around the level actor.
bool CollShapeLevel::intersectPoint(const VEC3 &p, CollResult *r)
{
	const f32 *at = r->actorB->positionPtr;
	if (!(p.x > at[0] - size.x && p.x < at[0] + size.x && p.y > at[1] - size.y && p.y < at[1] + size.y))
		return false;
	return keep(r, (at[1] - size.y) - p.y, p, VEC3(0, -1, 0));
}

// 0x002F5750 -> 0x002F5760: the same for a sphere (the rectangle widened by the radius); the point is at the
// level's height under the sphere.
bool CollShape::intersectSphereLevel(CollShape *sphere, CollShape *level, CollResult *r)
{
	VEC3 c = centre(sphere, r->actorA);
	f32 radius = sphere->boundingRadius;
	const f32 *at = r->actorB->positionPtr;
	if (!(c.x > at[0] - (level->size.x + radius) && c.x < at[0] + level->size.x + radius
	      && c.y > at[1] - level->size.y - radius && c.y < at[1] + level->size.y + radius))
		return false;
	return keep(r, ((at[1] - c.y) - radius) - level->size.y, VEC3(c.x, at[1], c.z), VEC3(0, -1, 0));
}

// 0x0017E2D0: either end of the capsule inside (intersectPoint).
bool CollShapeLevel::intersectCapsule(CollShape *c, CollResult *r)
{
	VEC3 top, bottom;
	((CollShapeCapsule *)c)->calcEndpoints(r->actorA, &top, &bottom);
	return intersectPoint(top, r) || intersectPoint(bottom, r);
}

// 0x0017E350: a green box of the level's size.

// ---- points (unused) ------------------------------------------------------------------------------------
// <collshape type="points"><point xyz="x y z"/>...</collshape>: up to 10 points in the actor's frame, each
// tested as a point against the other shape.

class CollShapePoints : public CollShape {     // vtable 0x00376580
	VEC3 points[10];                    // +0x68
	int count;                          // +0xE0
};

// 0x0017FDC4: the attributes, then the <point> children. The size grows to hold the points, but the Z
// maximum is written into size.y.
void CollShapePoints::read(const BXML::Node *node)
{
	CollShape::read(node);
	for (const BXML::Node *child = node->getChild(); child != nullptr; child = child->getSibling()) {
		if (strcmp(child->getName(), "point") != 0 || count >= 10)
			continue;
		VEC3 p = child->findAttribute("xyz")->vec3();
		points[count] = p;
		size.x = std::max(size.x, p.x);
		size.y = std::max(size.y, p.y);
		if (p.z > size.z)
			size.y = p.z;
		boundingRadius = std::max(boundingRadius, ::length(p));
		count++;
	}
}

// 0x00217430: every point (through actorA's matrix) against the other shape; the last point that hit is
// the result's part (its number + 1).
bool CollShape::intersectPoints(CollShapePoints *shape, CollShape *other, CollResult *r)
{
	bool hit = false;
	for (int i = 0; i < shape->count; i++) {
		VEC3 p = r->actorA->getMatrixSim() * shape->points[i];
		if (other->intersectPoint(p, r)) {
			hit = true;
			r->part = i + 1;
		}
	}
	return hit;
}

bool CollShapePoints::intersect(CollShape *other, CollResult *r) { return intersectPoints(this, other, r); }   // 0x0017FF1C
// 0x0017FBF0, 0x0017FC44, 0x0017FC98, 0x002173DC: swap, then intersectPoints (a point set is always tested
// from its own side). 0x0017FCEC draw: a green line 20 units long at each point.

// ---- edges (unused) -------------------------------------------------------------------------------------
// "edges/<file>.edge" (docs/formats.md): 2D segments in the actor's X/Y plane, by columns 16 units wide.

class CollShapeEdges : public CollShape {      // vtable 0x0037644C
	const EdgeSegment *segments;        // +0x68 (x1, y1, x2, y2, length, nx, ny, distance)
	f32 originX, originY;               // +0x6C
	f32 width, height;                  // +0x74
	int segmentCount, columnCount;      // +0x7C
	const u16 (*columns)[32];           // +0x84 [0] = cell count, then segment numbers
};

// 0x0017DFD8 setProperty: "file" loads. 0x0017E03C: the bounding sphere is centred on the outline's box.
void CollShapeEdges::load(const char *file)
{
	char path[128];
	strncpy(path, "edges/", 128);
	strncat(path, file, 128);
	strncat(path, ".edge", 128);
	const u32 *data = (const u32 *)Resource::getFile(path);
	width = as_f32(data[1]);
	height = as_f32(data[2]);
	originX = as_f32(data[3]);
	originY = as_f32(data[4]);
	offset.x = originX + width * 0.5f;
	offset.y = originY + height * 0.5f;
	segmentCount = data[5];
	columnCount = data[6];
	segments = (const EdgeSegment *)(data + 7);
	columns = (const u16 (*)[32])(segments + segmentCount);
	size = VEC3(width * 0.5f, height * 0.5f, 0);
	boundingRadius = ::length(size);
}

static u16 s_tested[64];                // 0x004C88FC segments already tested by this call
static int s_testedCount;               // 0x0038E28C

// 0x002F54B4: the column under the sphere's actor (X relative to the edges' actor), each of its segments
// once: a ray from the segment's start along it against the sphere (a sphere hit within the segment's
// length); the depth is measured from the sphere's actor to that point, the normal is the segment's.
bool CollShape::intersectSphereEdges(CollShape *sphere, CollShapeEdges *edges, CollResult *r);
// 0x002F5054 intersectPointEdges, 0x002F587C intersectCapsuleEdges: the same column walk for a point and for
// the capsule's segment. 0x002F5044 CollShapeEdges::intersectPoint; 0x0017E170 intersect; 0x0017E028
// intersectEdges and 0x0017E030 intersectSkeleton: false. 0x0017E038 draw: nothing.

// ---- skeletons (unused) ---------------------------------------------------------------------------------
// "prefix", "numBones", "base": one sphere per bone "<prefix>_<n>" (n < numBones) of the actor's first model,
// at the bone, of radius bone scale × base.

class CollShapeSkeleton : public CollShape {   // vtable 0x00376744
	int numBones;                       // +0x268
	f32 base;                           // +0x26C
	char prefix[32];                    // +0x270
};

// 0x001831C0
void CollShapeSkeleton::setProperty(const BXML::Attribute *a)
{
	if (strcmp(a->name, "base") == 0)
		base = a->number();
	else if (strcmp(a->name, "numBones") == 0)
		numBones = a->integer();
	else if (strcmp(a->name, "prefix") == 0)
		strcpy(prefix, a->string());
	else
		CollShape::setProperty(a);
}

// 0x002F6180: a sphere against each bone's sphere (a CollShapeSphere built on the stack, see the
// constructor) until one hits; the bone's index is the result's part.
bool CollShape::intersectSphereSkeleton(CollShape *sphere, CollShapeSkeleton *skeleton, CollResult *r)
{
	ModelSet *models = r->actorB->model;                        // Actor +0x138
	if (models == nullptr)
		return false;
	bool hit = false;
	for (int i = 0; i < skeleton->numBones && !hit; i++) {
		char bone[64];
		sprintf(bone, "%s_%u", skeleton->prefix, i);
		int idx = models->getModel(0)->getBoneIdx(bone);
		VEC3 scale;
		MTX34 m;
		if (!(models->getModel(0)->getBoneLocalScale(idx, &scale) & models->getModel(0)->getBoneMatrix(idx, &m)))
			continue;
		CollShapeSphere bs;
		bs.offset = m * VEC3(0, 0, 0);
		bs.relative = false;
		bs.boundingRadius = scale.x * skeleton->base;
		hit = intersectSphereSphere(sphere, &bs, r);
		if (hit)
			r->part = idx;
	}
	return hit;
}

// 0x002F6714: bone spheres against bone spheres. The bone indices of the second skeleton come from actorA's
// model, but their scales and matrices are read from actorB's model (the first one's), then moved by
// actorA's matrix.
bool CollShape::intersectSkeletonSkeleton(CollShapeSkeleton *a, CollShapeSkeleton *b, CollResult *r);

// 0x0018327C, 0x0018328C, 0x002F5E10, 0x002F6704: to the shared tests. 0x00183474 intersect. 0x002F5E20
// intersectPointSkeleton, 0x002F6360 intersectCapsuleSkeleton: the same bone walk for a point and a capsule.
// 0x0018329C draw: a green box for each bone.

// 0x003103A4 __sti___13_collision_cpp: the static constructors (s_tested).
