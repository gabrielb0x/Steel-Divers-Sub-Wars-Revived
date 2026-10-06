/* What the Pawn code of the mods shares (compiled by tools/pawn2pasm.py): the natives of the game
 * (decomp/pawn/natives.inc), Float operators on the game's float natives, vectors and angles. */

#include "natives.inc"

native Float:operator*(Float:oper1, Float:oper2) = floatmul;
native Float:operator/(Float:oper1, Float:oper2) = floatdiv;
native Float:operator+(Float:oper1, Float:oper2) = floatadd;
native Float:operator-(Float:oper1, Float:oper2) = floatsub;

stock Float:operator-(Float:oper)
{
    return Float:(_:oper ^ cellmin);
}

stock bool:operator==(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) == 0;
}

stock bool:operator!=(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) != 0;
}

stock bool:operator>(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) > 0;
}

stock bool:operator>=(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) >= 0;
}

stock bool:operator<(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) < 0;
}

stock bool:operator<=(Float:oper1, Float:oper2)
{
    return floatcmp(oper1, oper2) <= 0;
}

/* Collision types (actorSetCollisionType; a check mask selects the types an actor collides with). */
const COLL_MAP = 0x1;               // map, fences, doors (map.p, surface_land.p ...)
const COLL_PLAYER = 0x2;            // this console's player (pscope_player.p)
const COLL_NPC = 0x4;               // computer subs of this console (surface_sub.p)
const COLL_TORPEDO_NPC = 0x8;       // torpedoes of the computer subs, and the copies of the others'
const COLL_TORPEDO = 0x10;          // this console's player's torpedoes
const COLL_MINE = 0x2000;
const COLL_SUB = 0x40000;           // every sub: this console's (with 0x2 or 0x4) and the others' copies
const COLL_REMOTE = 0x80000;        // copies of the subs of the other consoles (netplay_dummy_sub.p)

const Float:PI = 3.1415926;

stock Float:fabs(Float:value)
{
    return value < 0.0 ? -value : value;
}

stock Float:fmin(Float:a, Float:b)
{
    return a < b ? a : b;
}

stock Float:fmax(Float:a, Float:b)
{
    return a > b ? a : b;
}

stock Float:fclamp(Float:value, Float:low, Float:high)
{
    return value < low ? low : (value > high ? high : value);
}

/* An angle brought back to -PI..PI. */
stock Float:wrapAngle(Float:angle)
{
    while (angle > PI)
        angle = angle - 2.0 * PI;
    while (angle < -PI)
        angle = angle + 2.0 * PI;
    return angle;
}

/* The game's yaw of a direction: forward is (sin yaw, 0, cos yaw) (vecRotateY of surface_sub.p). */
stock Float:yawOf(const Float:direction[3])
{
    return floatatan2(direction[0], direction[2]);
}

stock headingOf(Float:direction[3], Float:yaw)
{
    floatvecset(direction, floatsin(yaw, 0), 0.0, floatcos(yaw, 0));
}

stock Float:distance(const Float:a[3], const Float:b[3])
{
    new Float:d[3];
    floatvecsubto(d, a, b);
    return floatveclength(d);
}

stock Float:distance2D(const Float:a[3], const Float:b[3])
{
    new Float:d[3];
    floatvecsubto(d, a, b);
    d[1] = 0.0;
    return floatveclength(d);
}

stock Float:frandom()
{
    return floatrnd();
}
