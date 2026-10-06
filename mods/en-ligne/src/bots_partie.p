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
 * own (BOT_NODE + k, whose player.<node>.team and .name are set here).
 *
 * The bots are told as players are: "Vous avez touché <bot> !" for the player who hits one, "<bot> vous
 * attaque !" for the player one hits, "<bot> a été coulé !" for everyone, and the kill for its player.
 */

// @target amx/game_state.amx
// @call 0x3fec getTeamPlayerCount(team)
// @call 0x442c getPlayerTeam(node)
// @call 0x45cc incrementKills(node)
// @call 0x6f44 scheduleCheckGameOver(node, time, replayNode, replaySync)    public @scheduleCheckGameOver

#include "sdsw.inc"

const BOT_NODE = 0x7b070000;         // the bot k is "node" BOT_NODE + k (not a node id of Pia: 0xc00001 and up)

/* checkGameOverTeamBattle: the players of a team afloat, and its bots. */
forward teamRemaining(team);
public teamRemaining(team)
{
    new count = getTeamPlayerCount(team);
    if (sysGetGlobal("server.bots"))
        count += sysGetGlobal(team == 1 ? "bots.alive1" : "bots.alive2");
    return count;
}

/* The bot k as a player for the game: player.<node>.name (server.bots.name<k>) and .team. */
botAsPlayer(k, team)
{
    new name[48];
    new value[96];
    new node = BOT_NODE + k;
    strformat(name, sizeof name, false, "server.bots.name%d", k);
    sysGetGlobalArray(name, value, sizeof value);
    strformat(name, sizeof name, false, "player.%x.name", node);
    sysSetGlobalArray(name, value, sizeof value);
    if (team) {
        strformat(name, sizeof name, false, "player.%x.team", node);
        sysSetGlobal(name, team);
    }
    return node;
}

/* The bot k of this team is in the battle (bots_ia.p): every console knows its name and team. */
forward @botJoin(k, team);
public @botJoin(k, team)
{
    botAsPlayer(k, team);
}

isPlayerNode(node)
{
    return node > 0 && (node < BOT_NODE || node > BOT_NODE + 0xffff);
}

/* A torpedo hit the bot k of this team (its owner and sync id; the torpedo's node and sync id; who fired it,
 * as a node). Every console hears it: the last hit is kept for the kill and the replay, and the shooter, if
 * it is this console's player, is told as when it hits a player. */
forward @botHitBy(owner, sub, node, torpedo, shooter, k, team, homing);
public @botHitBy(owner, sub, node, torpedo, shooter, k, team, homing)
{
    new name[48];
    strformat(name, sizeof name, false, "bots.hit.%x.%d", owner, sub);
    sysSetGlobal(name, node);
    strformat(name, sizeof name, false, "bots.hitsync.%x.%d", owner, sub);
    sysSetGlobal(name, torpedo);
    strformat(name, sizeof name, false, "bots.hitby.%x.%d", owner, sub);
    sysSetGlobal(name, shooter);
    new bot = botAsPlayer(k, team);
    if (shooter != netGetNodeId() || getPlayerTeam(shooter) == team)
        return;
    // as pscope_player.p @eventMessageWeaponHitTorp for its shooter: "Vous avez touché <bot> !", and the hit
    // on the HUD (func_7b8c of the bot shows it when the bot is this console's)
    sysCallPublic(UID_MESSAGE_QUEUE, "@pushTargetHitMessage", bot, shooter);
    if (owner != shooter)
        sysCallPublic(UID_HUD, homing ? "@homingHit" : "@hit");
}

/* The bot k's torpedo hit a player: "<bot> vous attaque !" for that player (@eventMessageWeaponHitTorp only
 * says it of players). */
forward @botAttacks(victim, shooter);
public @botAttacks(victim, shooter)
{
    if (victim != netGetNodeId() || isPlayerNode(shooter) || shooter < BOT_NODE)
        return;
    botAsPlayer(shooter - BOT_NODE, 0);
    sysCallPublic(UID_MESSAGE_QUEUE, "@pushHitByShooterMessage", shooter);
}

/* The bot k of this team sank (bots_ia.p, its owner's node and its sync id). Every console hears it. */
forward @botDown(team, owner, sub, k);
public @botDown(team, owner, sub, k)
{
    new alive[16];
    alive = team == 1 ? "bots.alive1" : "bots.alive2";
    sysSetGlobal(alive, max(sysGetGlobal(alive) - 1, 0));
    // the HUD's team counter, bots included (bots_hud.pasm)
    new players = getTeamPlayerCount(team);
    sysCallPublic(UID_HUD, "@setTeamCount", team, players);
    // as a player's death (reportDeath): "<bot> a été coulé !" for everyone, and the kill for its shooter
    new bot = botAsPlayer(k, team);
    new name[48];
    new format[96];
    new botName[96];
    new text[96];
    sysGetString(format, "sub_sunk", sizeof format);
    strformat(name, sizeof name, false, "player.%x.name", bot);
    sysGetGlobalArray(name, botName, sizeof botName);
    strformat(text, sizeof text, false, format, botName);
    sndSE(0x100004c, 0, false);
    if (!sysGetGlobal("player.exit"))
        sysCallPublicf(UID_MESSAGE_QUEUE, "@doPush", "scccscccc", text, 0, -1, 120, "LOG_NORMAL", 1, 0, 2, 0);
    strformat(name, sizeof name, false, "bots.hitby.%x.%d", owner, sub);
    new shooter = sysGetGlobal(name);
    if (isPlayerNode(shooter) && getPlayerTeam(shooter) != team)
        incrementKills(shooter);
    // the end of the battle in a second, and its replay: the torpedo that sank it
    strformat(name, sizeof name, false, "bots.hit.%x.%d", owner, sub);
    new torpedoNode = sysGetGlobal(name);
    strformat(name, sizeof name, false, "bots.hitsync.%x.%d", owner, sub);
    new torpedo = sysGetGlobal(name);
    new time[2];
    netGetSessionTime(time);
    scheduleCheckGameOver(bot, time[1], torpedoNode, torpedo);
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
