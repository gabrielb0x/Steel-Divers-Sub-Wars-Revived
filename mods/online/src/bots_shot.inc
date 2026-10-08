/* The hits of the computer subs' torpedoes (bots_pilot.p sets their prop botshot), for surface_torpedo and
 * surface_torpedo_p_homing (bots_torpedo.p, bots_homing.p).
 *
 * The game's torpedoes of computer subs ("enemy") only hit this console's player for 10, whatever its team,
 * and ignore the computer subs (they compare the sub they hit with itself: surface_torpedo.p @eventCollide,
 * arg0 != npcActorId of arg0) and the players of the other consoles (it damages UID_PLAYER, this console's
 * player, who checks that the hit was for it). Ours hit like a player's: the target's console takes the hit
 * (the player's @eventMessageWeaponHitTorp, the owner's @torpedoHitOnNpcToOwner) with the damage of the
 * torpedo, teammates and the shooter's own sub are passed through, and the shooter is marked as a computer
 * sub (no kill counted for this console's player). */

/* 0: not ours (the game's code), 1: passed through, 2: hit (explode), 3: hit this console's player */
botHit(other, const Float:point[3], Float:toPlayer, Float:toBot, homing)
{
    new type = actorGetCollisionType(other);
    new shooter = 0;
    actorGetPropInt("actor_id", shooter, 0);
    if (other == shooter)
        return 1;
    if (type & (COLL_MAP | COLL_MINE)) {
        sysCallPublic(UID:other, "@torpedoHit", _:point[0], _:point[1], _:point[2], _:toBot, 0, 0);
        return 2;
    }
    if (!(type & (COLL_PLAYER | COLL_NPC | COLL_REMOTE)))
        return 1;                                       // torpedoes, items
    new team = 0;
    new mine = 0;
    actorGetPropInt("teamColor", team, other);
    actorGetPropInt("teamColor", mine, 0);
    if (team && team == mine)
        return 1;
    if (sysGetGlobal("mode.gameover") || sysGetGlobal("player.timeOver"))
        return 2;
    // the shooter's node is its console's: the game finds the torpedo by (node, sync id) for the replay; the
    // player of that console does not take it as friendly fire (anti-ff hook of bots_player.pasm)
    new node = netGetNodeId();
    new npc = 0;
    actorGetPropInt("npc", npc, other);
    if (npc) {
        new owner = actorGetSyncController(other);
        new id = 0;
        actorGetPropInt("npcActorId", id, other);
        // (owner, shooter's node, sub, x, y, z, damage, 0, opponent is a computer sub, same team, critical,
        //  homing, shooter is a computer sub)
        netCallPublic(UID_MODE, "@torpedoHitOnNpcToOwner", owner, node, id, _:point[0], _:point[1], _:point[2],
                      _:toBot, 0, 1, 0, 0, homing, 1);
        return 2;
    }
    new victim = 0;
    actorGetPropInt("nodeid", victim, other);
    new torpedo = actorGetSyncID(0);
    // (torpedo, target's node, damage, shooter's node, x, y, z, target is a computer sub, friendly fire,
    //  shooter is a computer sub)
    netCallPublic(UID_PLAYER, "@eventMessageWeaponHitTorp", torpedo, victim, _:toPlayer, node,
                  _:point[0], _:point[1], _:point[2], 0, 0, 1);
    if (sysGetGlobal("server.bots"))
        netCallPublic(UID_GAME_STATE, "@botAttacks", victim, shooterNode());    // "<bot> is attacking you!"
    return (type & COLL_PLAYER) ? 3 : 2;
}

const BOT_NODE = 0x7b070000;         // the bot k is "node" BOT_NODE + k for the game (bots_game_state.p)

/* Who fired this torpedo, as the game names players: a player's node, or BOT_NODE + k for the bot k; -1 for
 * a computer sub of the game. */
shooterNode()
{
    new shot = 0;
    actorGetPropInt("botshot", shot, 0);
    if (!shot)
        return netGetNodeId();
    new shooter = 0;
    new k = 0;
    actorGetPropInt("actor_id", shooter, 0);
    actorGetPropInt("botIndex", k, shooter);
    return k ? BOT_NODE + k : -1;
}

/* A torpedo of this console (a player's or a bot's) hits a computer sub: every console notes it, for the
 * kill, the messages and the replay of the end of the battle (bots_game_state.p @botHitBy). */
noteBotHit(other, homing)
{
    new type = actorGetCollisionType(other);
    new npc = 0;
    actorGetPropInt("npc", npc, other);
    if (!npc || !(type & (COLL_NPC | COLL_REMOTE)) || !sysGetGlobal("server.bots"))
        return;
    new k = 0;
    new team = 0;
    actorGetPropInt("botIndex", k, other);
    actorGetPropInt("teamColor", team, other);
    netCallPublic(UID_GAME_STATE, "@botHitBy", actorGetSyncController(other), actorGetSyncID(other),
                  netGetNodeId(), actorGetSyncID(0), shooterNode(), k, team, homing);
}
