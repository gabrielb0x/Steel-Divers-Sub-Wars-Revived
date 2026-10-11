// source/amx/amxvector.cpp (amxvector.o), source/amx/amxdynamics.cpp (amxdynamics.o) and source/amx/amxbb.cpp
// (amxbb.o): the scripts' vector natives (natives_Vector), the rigid-body step their vehicles use
// (natives_Dynamics), and a debug listing (natives_BB).
//
// Reconstructed by hand from decomp/raw/source/amx/{amxvector,amxdynamics,amxbb}.cpp and the disassembly.
// Not compilable on its own. Vectors are 3 cells of floats; `in` reads one with AMXLoader::getVector3,
// `out` gives its address.

#define in(i)  self->getVector3(p[i])
#define out(i) ((float *)self->getAddr(p[i], 0))
#define SELF   AMXLoader *self = AMXLoader::getCurrentLoader()

// ---- amxvector.cpp (registered by amx_VectorInit 0x00171A24) -------------------------------------------

static cell n_floatvecset(AMX *, const cell *p) { SELF; cell *v = (cell *)out(1); v[0] = p[2]; v[1] = p[3]; v[2] = p[4]; return 0; }  // 0x00322D28
static cell n_floatveczero(AMX *, const cell *p) { SELF; cell *v = (cell *)out(1); v[0] = v[1] = v[2] = 0; return 0; }               // 0x00322E50
static cell n_floatvecadd(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(2); v[0] += a.x; v[1] += a.y; v[2] += a.z; return 0; }   // 0x003226A4
static cell n_floatvecsub(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(2); v[0] -= a.x; v[1] -= a.y; v[2] -= a.z; return 0; }   // 0x00322D68

// 0x0032277C / 0x00322DBC: dest = a + b, dest = a - b.
static cell n_floatvecaddto(AMX *, const cell *p) { SELF; float *d = out(1), *a = out(2), *b = out(3); for (int i = 0; i < 3; i++) d[i] = a[i] + b[i]; return 0; }
static cell n_floatvecsubto(AMX *, const cell *p) { SELF; float *d = out(1), *a = out(2), *b = out(3); for (int i = 0; i < 3; i++) d[i] = a[i] - b[i]; return 0; }

// In place, component by component (0x00322A44, 0x003228EC) or by a scalar (0x00322CD4, 0x00322968).
static cell n_floatvecmul(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(1), b = in(2); v[0] = a.x * b.x; v[1] = a.y * b.y; v[2] = a.z * b.z; return 0; }
static cell n_floatvecdiv(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(1), b = in(2); v[0] = a.x / b.x; v[1] = a.y / b.y; v[2] = a.z / b.z; return 0; }
static cell n_floatvecscale(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(1); float s = amx_ctof(p[2]); v[0] = a.x * s; v[1] = a.y * s; v[2] = a.z * s; return 0; }
static cell n_floatvecdivide(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(1); float s = amx_ctof(p[2]); v[0] = a.x / s; v[1] = a.y / s; v[2] = a.z / s; return 0; }

// 0x003226F8: vector += add * scale; 0x00322810: dest = source * scale.
static cell n_floatvecaddscale(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(1), b = in(2); float s = amx_ctof(p[3]); v[0] = a.x + b.x * s; v[1] = a.y + b.y * s; v[2] = a.z + b.z * s; return 0; }
static cell n_floatveccopyscale(AMX *, const cell *p) { SELF; float *v = out(1); VEC3 a = in(2); float s = amx_ctof(p[3]); v[0] = a.x * s; v[1] = a.y * s; v[2] = a.z * s; return 0; }

// 0x00322864: dest = a x b.
static cell n_floatveccross(AMX *, const cell *p)
{
	SELF;
	float *d = out(1);
	VEC3 a = in(2), b = in(3);
	d[0] = a.y * b.z - a.z * b.y;
	d[1] = a.z * b.x - a.x * b.z;
	d[2] = a.x * b.y - a.y * b.x;
	return 0;
}

static cell n_floatvecdot(AMX *, const cell *p) { SELF; VEC3 a = in(1), b = in(2); return amx_ftoc(a.x * b.x + a.y * b.y + a.z * b.z); }   // 0x003229C0
static cell n_floatveclength(AMX *, const cell *p) { SELF; VEC3 a = in(1); return amx_ftoc(sqrtf(a.x * a.x + a.y * a.y + a.z * a.z)); }   // 0x00322A18

// 0x00322ABC: dest = source / |source| (no check for zero).
static cell n_floatvecnormalize(AMX *, const cell *p)
{
	SELF;
	float *d = out(1), *s = out(2);
	float k = 1.0f / sqrtf(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]);
	VEC3 v = {s[0] * k, s[1] * k, s[2] * k};
	d[0] = v.x; d[1] = v.y; d[2] = v.z;
	return 0;
}

// 0x00322B48: dest = vector rotated by `radians` about `axis` (normalised): the rotation matrix of the
// axis and angle (Rodrigues), its sine and cosine from nn::math's table (SinCosFIdx, the angle turned into
// the table's index), applied by MTX34MultVec (0x0023676C).
static cell n_floatvecrotrad(AMX *, const cell *p)
{
	SELF;
	float *d = out(1);
	VEC3 v = in(2), axis = normalise(in(3));
	float s, c;
	nn::math::SinCosRad(&s, &c, amx_ctof(p[4]));
	float t = 1 - c;
	MTX34 m = {
		c + t * axis.x * axis.x,          t * axis.x * axis.y - s * axis.z, t * axis.x * axis.z + s * axis.y, 0,
		t * axis.x * axis.y + s * axis.z, c + t * axis.y * axis.y,          t * axis.y * axis.z - s * axis.x, 0,
		t * axis.x * axis.z - s * axis.y, t * axis.y * axis.z + s * axis.x, c + t * axis.z * axis.z,          0,
	};
	VEC3 r = m * v;
	d[0] = r.x; d[1] = r.y; d[2] = r.z;
	return 0;
}

// ---- amxdynamics.cpp (amx_DynamicsInit 0x0017262C) -----------------------------------------------------

// 0x003220C8: one step of a body: velocity and spin damped (times 1 - damping), the position and rotation
// moved by them, then gravity added to the vertical velocity. Nothing while the replay plays.
static cell n_dynamicsUpdateN(AMX *, const cell *p)
{
	if (g_world->replaying)
		return 0;
	SELF;
	VEC3 position = in(1), velocity = in(2), rotation = in(3), spin = in(4);
	float damping = amx_ctof(p[5]), spinDamping = amx_ctof(p[6]);
	velocity = velocity - velocity * damping;
	position = position + velocity;
	velocity.y += amx_ctof(p[7]);
	spin = spin - spin * spinDamping;
	rotation = rotation + spin;
	memcpy(out(1), &position, 12);
	memcpy(out(2), &velocity, 12);
	memcpy(out(3), &rotation, 12);
	memcpy(out(4), &spin, 12);
	return 0;
}

// 0x00321F1C: a force applied at a point: the torque (point - position) x force, in the calling actor's own
// frame (its inverse matrix), times inverseInertia, goes to the spin; the force to the velocity (or, with
// toPosition, straight to the position).
static cell n_dynamicsAddForceN(AMX *, const cell *p)
{
	SELF;
	Actor *actor = self->getActor(0);
	VEC3 position = in(1), spin = in(3), inverseInertia = in(4), point = in(5), force = in(6);
	VEC3 torque = cross(point - position, force);
	VEC3 local = actor->getInverseMatrix()->rotate(torque);
	float *target = p[7] != 0 ? out(1) : out(2);
	target[0] += force.x;
	target[1] += force.y;
	target[2] += force.z;
	float *s = out(3);
	s[0] = spin.x + local.x * inverseInertia.x;
	s[1] = spin.y + local.y * inverseInertia.y;
	s[2] = spin.z + local.z * inverseInertia.z;
	return 0;
}

// ---- amxbb.cpp (amx_BBInit 0x001711B0) -----------------------------------------------------------------

// 0x00321C40: bbls(): a debug listing of the actors around "player" (radius 30), each with the name of
// its script — always "UNIMPLEMENTED" — after its last '/'. The printing is gone.
static cell n_bbls(AMX *, const cell *);

// n_bbswitch: does nothing the retail scripts could see.
