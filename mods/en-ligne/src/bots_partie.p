/* game_state: the end of a battle against the server's bots (see bots_salon.pasm).
 *
 * The game ends a battle when fewer than two teams have players afloat (checkGameOverTeamBattle, on the host);
 * its bots do not count. Against the server's bots, a team's bots afloat count with its players (bots.alive1,
 * bots.alive2: set by bots_bataille.pasm, lowered by @botDown when a bot sinks).
 *
 * The game only reports a computer sub sunk by a torpedo (@eventMessageAISubDead), not by an explosion
 * (@explosionHitOnNpc), and finds its team again by its sync id, which can fail: the bots' pilot (bots_ia.p)
 * says itself, once, that it sank, with its team (@botDown).
 *
 * The replay at the end of a battle: each death of a player is scheduled with the torpedo that sank it
 * (@scheduleCheckGameOver(node, time, torpedo's node, torpedo's sync id), from @eventMessageSubDead), and the
 * game shows the run of the torpedo of the last one sunk in the losing team (checkGameOverTeamBattle); the team
 * of a death is that of its node (player.<node>.team). A bot's death had no torpedo and no node: no replay when
 * a bot was the last one sunk, that is when the players won. Now every torpedo that hits a bot says so
 * (@botHitBy, bots_tir.inc), and a bot's death is scheduled as a player's, with that torpedo and a node of its
 * own team (BOT_NODE + team, whose player.<node>.team is set here).
 */

// @target amx/game_state.amx
// @call 0x3fec getTeamPlayerCount(team)
// @call 0x6f44 scheduleCheckGameOver(node, time, replayNode, replaySync)    public @scheduleCheckGameOver

#include "sdsw.inc"

const BOT_NODE = 0x7b070000;         // not a node id of Pia (those are 0xc00001 and up)

/* checkGameOverTeamBattle: the players of a team afloat, and its bots. */
forward teamRemaining(team);
public teamRemaining(team)
{
    new count = getTeamPlayerCount(team);
    if (sysGetGlobal("server.bots"))
        count += sysGetGlobal(team == 1 ? "bots.alive1" : "bots.alive2");
    return count;
}

/* A torpedo hit a computer sub (the sub's owner and sync id; the torpedo's node and sync id): the last one
 * that hit it, for the replay if it sinks. Every console hears it. */
forward @botHitBy(owner, sub, node, torpedo);
public @botHitBy(owner, sub, node, torpedo)
{
    new name[48];
    strformat(name, sizeof name, false, "bots.hit.%x.%d", owner, sub);
    sysSetGlobal(name, node);
    strformat(name, sizeof name, false, "bots.hitsync.%x.%d", owner, sub);
    sysSetGlobal(name, torpedo);
}

/* A bot of this team sank (bots_ia.p, its owner's node and its sync id). Every console hears it. */
forward @botDown(team, owner, sub);
public @botDown(team, owner, sub)
{
    new alive[16];
    alive = team == 1 ? "bots.alive1" : "bots.alive2";
    sysSetGlobal(alive, max(sysGetGlobal(alive) - 1, 0));
    // the HUD's team counter, bots included (bots_hud.pasm)
    new players = getTeamPlayerCount(team);
    sysCallPublic(UID_HUD, "@setTeamCount", team, players);
    // the end of the battle in a second, and its replay: the torpedo that sank it
    new name[48];
    new node = BOT_NODE + team;
    strformat(name, sizeof name, false, "player.%x.team", node);
    sysSetGlobal(name, team);
    strformat(name, sizeof name, false, "bots.hit.%x.%d", owner, sub);
    new torpedoNode = sysGetGlobal(name);
    strformat(name, sizeof name, false, "bots.hitsync.%x.%d", owner, sub);
    new torpedo = sysGetGlobal(name);
    new time[2];
    netGetSessionTime(time);
    scheduleCheckGameOver(node, time[1], torpedoNode, torpedo);
}

main()
{
}

/* asm
; checkGameOverTeamBattle: getTeamPlayerCount(team) (func_3fec) -> teamRemaining(team), at both calls.
.hook 0x6854
    call @pw_teamRemaining
    .return

.hook 0x68bc
    call @pw_teamRemaining
    .return
*/
