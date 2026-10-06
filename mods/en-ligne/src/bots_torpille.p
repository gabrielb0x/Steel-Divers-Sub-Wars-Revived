/* surface_torpedo: the torpedoes of the computer subs hit like a player's (bots_tir.inc). */

// @target amx/surface_torpedo.amx
// @game Float:g_0dc0          damage (property "damage": 20, 25, 30 for the levels 1, 2, 3)
// @game g_13f0                exploded
// @game g_13f4                a copy of another console's torpedo
// @game g_1420                it hit this console's player (no second hit by its explosion)
// @call 0x6cdc torpedoExplode(now)    public @explode

#include "sdsw.inc"
#include "bots_tir.inc"

/* @eventCollide(other, point): 1 when the hit was ours. */
forward botTorpedoCollide(other, Float:point[3]);
public botTorpedoCollide(other, Float:point[3])
{
    new shot = 0;
    actorGetPropInt("botshot", shot, 0);
    if (!shot || g_13f4)
        return 0;
    if (g_13f0)
        return 1;
    new r = botHit(other, point, g_0dc0, g_0dc0, 0);
    if (r == 3)
        g_1420 = 1;
    if (r >= 2)
        torpedoExplode(0);
    return 1;
}

main()
{
}

/* asm
; @eventCollide(other, point): ours first.
.hook 0x528c
    push.s 0x10
    push.s 0xc
    push.c 8
    call @pw_botTorpedoCollide
    jzer @collide_game
    zero.pri
    retn
collide_game:
    .original
    .return
*/
