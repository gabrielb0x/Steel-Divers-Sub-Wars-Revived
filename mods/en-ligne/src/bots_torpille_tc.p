/* surface_torpedo_p_homing: the homing torpedoes of the computer subs hit like a player's (bots_tir.inc).
 * Online, the game's homing torpedo of a computer sub hits nothing at all: its @eventCollide only handles
 * them offline. */

// @target amx/surface_torpedo_p_homing.amx
// @game g_1418                a copy of another console's torpedo
// @game g_141c                exploded
// @game Float:g_1458          damageToNpc (70)
// @game Float:g_145c          damageToPlayer (30)
// @game g_148c                it hit this console's player
// @call 0x7f4c homingExplode()

#include "sdsw.inc"
#include "bots_tir.inc"

forward botTorpedoCollide(other, Float:point[3]);
public botTorpedoCollide(other, Float:point[3])
{
    new shot = 0;
    actorGetPropInt("botshot", shot, 0);
    if (g_1418)
        return 0;
    if (!shot) {
        if (!g_141c)
            noteBotHit(other, 1);                          // a player's torpedo: the game's code hits
        return 0;
    }
    if (g_141c)
        return 1;
    new r = botHit(other, point, g_145c, g_1458, 1);
    if (r == 3)
        g_148c = 1;
    if (r == 2)
        noteBotHit(other, 1);
    if (r >= 2)
        homingExplode();
    return 1;
}

main()
{
}

/* asm
; @eventCollide(other, point): ours first.
.hook 0x69b0
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
