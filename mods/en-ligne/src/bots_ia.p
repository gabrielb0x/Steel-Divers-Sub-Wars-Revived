/* surface_sub: the computer subs of the online battles fly and fight like players.
 *
 * Every computer sub of an online battle (the bots of the battles against the server's bots, and those the
 * game adds to fill the teams) gets this pilot instead of the game's own bot, which patrols around its spawn
 * point, fires straight ahead every 250 frames whatever it faces, goes through walls and subs (it sets its
 * position without ever looking at its collisions) and only ever aims at players. The level
 * (server.bots.level: 1 normal, 2 difficile, 3 expert; difficile when the server does not say) sets how fast
 * it reacts and how precisely it aims. Offline (missions), surface_sub keeps the game's bot.
 *
 * The pilot moves the sub with the physics of a player's sub (pscope_player.p func_12184: thrust and drag,
 * turn rate that follows the stick with inertia, dive rate) and the characteristics of its submarine
 * (bxml/pscope_plyNN_stats: turning, acceleration, dive, torpedoes, masker), collides with the map and the
 * other subs (@eventCollide), looks ahead to steer clear of walls, and backs out when stuck. It fights any
 * enemy sub, player or computer: the most interesting one it can see, aimed at where it will be when the
 * torpedo gets there (its speed and turn rate, the torpedo's acceleration, in three dimensions), fired only
 * with a clear line and no teammate in the way, with the torpedoes and the reload of its submarine. It keeps
 * its distance, backs off when too close, dodges the torpedoes coming at it by changing depth and heading,
 * fires homing torpedoes at targets that evade, and when its hull is low it backs away still firing, then
 * hides under its masker and flees. The torpedoes are the players' (surface_torpedo_lv0N,
 * surface_torpedo_p_homing), whose hits bots_torpille.pasm sends to their target like a player's.
 *
 * It starts where a player would (the spawn points of the map, bxml/sdsw_spawn_*: the slots the players leave
 * free), steers by its whole hull (a capsule 550 long: it looks ahead from its nose and slows down for walls in
 * time), and does not fight the same way twice: each bot has its own temper (distance, aggression, side, depth),
 * changes maneuver every few seconds (holds, circles, closes in, breaks off, changes depth, stops short), aims
 * at where the target goes if it keeps turning, goes straight, or dodges the way it has dodged so far (learned
 * during the battle and the session, per player), and dodges torpedoes in a direction of its own choosing. It
 * takes a crew as a player does (server.bots.crew<k>): the crew changes the ratings of its submarine and gives
 * it their abilities (lock-on and sonar range, cheaper or longer masker, repair, air; with the update, the
 * team's repair, hiding from the sonar when hurt, the masker that starts by itself when a homing torpedo locks).
 */

// @target amx/surface_sub.amx
// @game g_11b4                the oil leak's (set when it starts, as @torpedoHit)
// @game g_11b8
// @game g_11c8                it leaks oil (the black smoke of a damaged sub)
// @game Float:g_11f0          throttle shown (wake, propeller), -1..1
// @game Float:g_1c68          life
// @game g_1c90                afloat; 0: sinking (func_ba34)
// @game Float:g_1c74          roll speed (hits)
// @game Float:g_1c78          speed of the game's movement (still used while sinking)
// @game Float:g_1c80[3]       where the last hit landed, in the sub's space (@torpedoHit)
// @game Float:g_1ca0[3]       position
// @game Float:g_1cc8          yaw
// @game Float:g_1e78          pitch
// @game Float:g_1e7c          roll
// @game g_1eac                frames before the sinking sub explodes (func_ba34)
// @game g_1f28                online battle
// @call 0x8668 torpedoHit(Float:x, Float:y, Float:z, Float:damage, exp, isOpponentNpc, critical, sameTeam, shooter, isHoming, fromNpc)    public @torpedoHit
// @game Float:g_3064[3]       velocity of the last frame (network sync)
// @game Float:g_3070[3]       rotation of the last frame (network sync: torque)

#include "sdsw.inc"

/* ---- skill of each level (index: server.bots.level) -------------------------------------------- */
//                          -   normal  difficile  expert
new const SEE_EVERY[] =   { 0,  10,     6,         3 };          // frames between two looks around
new const FIRE_PAUSE[] =  { 0,  40,     12,        0 };          // frames added to the reload
new const Float:MISS_ALLOWED[] = { 0.0, 90.0, 60.0, 45.0 };     // how far off the target a shot may pass
new const Float:DODGE[] = { 0.0, 0.35, 0.85, 1.0 };              // chance to see a torpedo coming
new const MANEUVER_MIN[] = { 0, 150,    75,        50 };          // frames of a maneuver, at least
new const MANEUVER_SPAN[] = { 0, 150,   110,       90 };          // and at most this much more
new const LEARNS[] =      { 0,  0,      1,         1 };           // learns how each player dodges

const Float:TORPEDO_ACCEL = 1.2;     // surface_torpedo.p main: func_2ef4(..., 1.2, ...)
const Float:TORPEDO_KEEP = 0.99;     // 1 - friction (0.01, func_1488)
const Float:LIN_DRAG = 0.038;        // linDrag of every pscope_plyNN_stats
const Float:DIVE_DRAG = 0.16;        // diveDrag
const Float:SURFACE = -70.0;         // highest point: under the waterline
const Float:HULL = 70.0;             // half the height of a sub, what a torpedo can miss by vertically
const Float:NOSE = 300.0;            // from the middle of the sub to its nose (capsule 550 long, 60 wide)
const Float:BEAM = 70.0;             // half its width, and some
const Float:NO_CLIMB = 1000.0;
const BOT_NODE = 0x7b070000;         // the bot k is node BOT_NODE + k for the game (bots_partie.p)

new lvl;                             // 0: the game's own bot (offline, or not a computer sub)
new started;
new sunk;
new botIndex;                        // k of server.bots.*<k>, 0 for a bot of the game
new Float:damageRate = 1.0;          // damage taken is multiplied by it, as a player's (table_damage_rate)
new maskerUses;
new hitWindow = 60;                  // frames without damage after a hit (and at the start), as a player
new collisionHit;
new bumpDamage;
new collideTime;
new frame;
new me;                              // actor id
new myTeam;
new Float:lifeMax;
new Float:lifeBefore;

// the submarine
new Float:maxTurn = 0.035;
new Float:accel = 0.36;
new Float:diveRate = 0.4;
new torpedoLevel = 1;
new torpedoMax = 6;
new torpedoes;
new replenishFrames = 180;
new fireInterval = 85;
new reload;
new homing;
new Float:maskerCost = 33.3;
new Float:air = 100.0;
new maskerTime;
new side = 1;                        // the tube of the next torpedo

// motion
new Float:vel[3];
new Float:yawRate;
new Float:throttle;
new Float:throttleWant;
new Float:yawWant;
new Float:yawSteer;
new Float:steerBefore;
new Float:steerRate;
new Float:depthWant = -300.0;
new Float:climbWant;                 // vertical speed wanted, NO_CLIMB: go to depthWant
new Float:pitch;
new Float:pitchRate;
new Float:forwardSpeed;
new brakeTime;
new Float:brake = 1.0;
new Float:brakeRate = 0.97;
new brakeFrames = 30;
new Float:diveDrag = 0.16;
new Float:tubeLocal[3] = { 39.0, -14.0, 111.0 };
new Float:push[3];
new Float:bump[3];
new bumpTime;
new lastBump = -10000;               // when it last touched the map
new Float:floorY = -100000.0;
new Float:stuckAt[3];
new stuckCheck;
new backOutTime;
new Float:backOutTurn;
new avoidSide;                       // the side it goes round an obstacle by: 1, -1, 0 none

// what it knows
new target = -1;
new targetSince;
new Float:tPos[3];
new Float:tVel[3];
new Float:tOmega;
new Float:tHistory[24];              // 8 positions, one per frame
new tHistoryCount;
new tHead;
new Float:tHeading;
new tTurning;                        // the way it turns: 1, -1, 0 straight
new tSwerve = -1000;                 // when it last changed the way it turns
new tVisible;
new Float:lastKnown[3];
new lastKnownTime;
new Float:goal[3];                   // where to go without a target
new goalValid;
new Float:wanderTo[3];
new mates[8];
new mateCount;
new hurtTime;
new contacts[8];                     // the subs its last ping found
new contactCount;
new contactAt = -10000;
new sonarIn;
new pickedItem = -1;
new container = -1;                  // a container it goes for
new homingIn;                        // frames before the homing torpedoes can be fired (120 + 15 after a shot, func_10e04)
new maskerIn;                        // frames before the masker can be used again (150 after one, periscope_move.p)
new emptyFor;                        // frames since its last torpedo (all are reloaded torpedoReplenishTime later)
new revealed = -1;                   // a masked enemy seen when it was hit
new revealedAt = -1000;
new lostAt = -10000;                 // when its target vanished under its masker
new Float:lostPos[3];
new Float:lostVel[3];
new blindShots;
new evadeTime;
new Float:evadeYaw;
new Float:evadeThrottle = 1.0;

// its temper, drawn when it starts: two bots never fight alike, nor one bot twice
new Float:pRange = 1.0;              // the distance it likes, times the usual
new Float:pAggro = 0.5;              // 0..1: how much it presses in
new pSide = 1;                       // the side it circles by, first
new Float:pDepth;                    // above (+) or below the target
new flank;                           // -1, 0, 1: the side it comes from when its teammates fight the same target
// the maneuver of the moment (combat)
const M_HOLD = 0;                    // face it at its distance
const M_CIRCLE = 1;                  // round it, then turn in to fire
const M_CLOSE = 2;                   // closer, then fire
const M_BREAK = 3;                   // away, then back
const M_DEPTH = 4;                   // another depth
const M_STOP = 5;                    // stops short (a shot led on its speed goes ahead of it)
new maneuver;
new maneuverUntil;
new Float:maneuverThrottle = 0.4;
new Float:depthShift;                // the depth it takes between two shots
new autoMaskerAt = -10000;           // when the crew's masker came on (autoMasker)
// how it leads a shot: 0 the target keeps turning, 1 it goes straight, 2 it dodges as it has so far
new predictMode;
new Float:iOmega;                    // turn rate of the prediction (intercept), then...
new Float:iOmega2;                   // ...after the target's reaction (mode 2)
new Float:iReact = 1000.0;
new Float:learnOmega;                // the way the target turns when fired at (rad a frame, toward its left > 0)
new learnCount;
new learnOf = -1;                    // the target it learnt it from
new watchShot = -1;                  // a shot it watches the target dodge: the frame it was fired

// its crew (server.bots.crew<k>): what the crew_stats of the game give a player
new Float:seeRange = 7000.0;         // lockOnLong: 8500
new Float:sonarRange = 15000.0;      // wideSonar: 20000
new crewRepair;
#if SDSW_VERSION >= 5200
new crewTeamRepair;
new crewHideSonar;
new mateRepairs;                     // a teammate with the team's repair within 2000
#endif
new crewAutoMasker;
new crewLongMasker;
new crewAirUp;
new crewCount;
new crewMembers[5] = { -1, -1, -1, -1, -1 };

forward Float:torpedoRange();
forward bool:hullClear(Float:yaw, Float:look);
forward Float:missNow(&frames);

/* ---- what the hooks call (asm at the end) ----------------------------------------------------- */

/* main, after func_e098 (the sub's properties): is it one of ours? */
forward botInit();
public botInit()
{
    new npc = 0;
    lvl = 0;
    if (!g_1f28)
        return 0;
    actorGetPropInt("npc", npc, 0);
    if (!npc)
        return 0;
    lvl = sysGetGlobal("server.bots.level");
    if (lvl < 1)
        lvl = 2;
    if (lvl > 3)
        lvl = 3;
    return lvl;
}

forward botLevel();
public botLevel()
{
    return lvl;
}

/* A bot of the server stays synced 215 frames after it sank (main), as the game's torpedoes do after they
 * explode: the replay at the end of the battle can show it (bots_partie.p @botDown). */
forward botKeepsSync();
public botKeepsSync()
{
    return lvl && sysGetGlobal("server.bots");
}

/* func_a848, every frame: 1 when the pilot moved the sub, 0 to let the game do it (sinking). */
forward botPilot();
public botPilot()
{
    if (!lvl)
        return 0;
    if (!g_1c90 || g_1c68 <= 0.01) {
        if (started && maskerTime)
            maskerOff();
        if (started && !sunk) {
            // its team loses a sub: every console hears it (bots_partie.p @botDown), whatever sank it
            sunk = 1;
            g_1eac = 0;                                 // no slow sinking: it blows up at once, as a player
            actorSetPropReal("life", 0.0, 0);
            if (sysGetGlobal("server.bots"))
                netCallPublic(UID_GAME_STATE, "@botDown", myTeam, netGetNodeId(), actorGetSyncID(0), botIndex);
        }
        return 0;
    }
    if (!started)
        start();
    frame++;
    collisionDamage();
    if (!g_1c90 || g_1c68 <= 0.01)
        return 0;
    actorSetPropReal("life", g_1c68, 0);               // seen by the others (synced), and by bots_partie
    // oil leaks below 40 % of the hull, as from a player's sub (netplay_dummy_sub.p: life < lifecapacity /
    // 2.5); the game's @torpedoHit starts it below 100, whatever the hull
    if (sysGetGlobal("server.bots")) {
        new leak = g_1c68 < lifeMax / 2.5;
        if (leak && !g_11c8) {
            g_11b4 = 9;
            g_11b8 = 0;
        }
        g_11c8 = leak;
    }
    timers();
    if (frame % SEE_EVERY[lvl] == me % SEE_EVERY[lvl])
        lookAround();
    follow();
    decide();
    if (frame % 3 == 0)
        steerClear();
    move();
    return 1;
}

/* What the pilot thinks, for tools/botsim.py: target, its position and velocity, turn rate, wanted heading,
 * throttle and depth, torpedoes, the last shot's elevation. */
new Float:lastMiss;
new holdReason;
new lastTorpedo;                    // the last torpedo fired
new Float:aimDir[3];                 // the last intercept
new Float:aimAt[3];
new aimFlight;
forward botDebug(Float:out[16]);
public botDebug(Float:out[16])
{
    out[0] = float(target);
    out[1] = tPos[0];
    out[2] = tPos[1];
    out[3] = tPos[2];
    out[4] = tVel[0];
    out[5] = tVel[1];
    out[6] = tVel[2];
    out[7] = tOmega;
    out[8] = yawWant;
    out[9] = throttleWant;
    out[10] = depthWant;
    out[11] = float(torpedoes);
    out[12] = lastMiss + float(holdReason) * 100000.0;    // why it held fire, and the last miss
    out[13] = yawSteer;
    out[14] = float(tVisible);
    out[15] = floorY;
    return 1;
}

/* The sub touches the map or another sub (Actor::procCollisions): normal points away from the other. */
forward @eventCollide(other, Float:point[3], Float:normal[3]);
public @eventCollide(other, Float:point[3], Float:normal[3])
{
    #pragma unused point
    if (!lvl || !started)
        return 0;
    new type = actorGetCollisionType(other);
    if (type & COLL_ITEM) {
        pickUp(other);
        return 0;
    }
    if (!(type & (COLL_MAP | COLL_SUB | COLL_REMOTE)))
        return 0;
    floatvecaddscale(push, normal, 5.0);
    bumpDamage = 1;
    bump = normal;
    bumpTime = 12;
    if (type & COLL_MAP)
        lastBump = frame;
    return 0;
}

/* A container, as a player picks one up (pscope_player.p @eventMessageLifeGet, @eventMessageHomingGet):
 * repair, a fifth of its hull (all of it when less than 20 is missing); or a homing torpedo, 3 at most.
 * Every console takes it away (bots_partie.p @botTakesItem), as the player's copy does on theirs. */
pickUp(item)
{
    if (!sysGetGlobal("server.bots") || pickedItem == item)
        return;
    pickedItem = item;
    new kind = 0;
    actorGetPropInt("itemNum", kind, item);
    if (kind == 1) {
        if (homing < 3)
            homing++;
        homingIn = max(homingIn, 15);
    } else {
        g_1c68 = lifeMax - g_1c68 >= 20.0 ? g_1c68 + lifeMax / 5.0 : lifeMax;
        lifeBefore = g_1c68;
    }
    new Float:p[3];
    actorGetPosition(p, item);
    netCallPublic(UID_GAME_STATE, "@botTakesItem", _:p[0], _:p[1], _:p[2]);
}

/* ---- start -------------------------------------------------------------------------------------- */

start()
{
    started = 1;
    me = actorGetID();
    actorGetPropInt("teamColor", myTeam, 0);
    readSubmarine();
    // a player's hull: 100, times the other team's size over its own when outnumbered (pscope_player.p
    // func_14f60, the bots counted as players: bots_joueur.pasm)
    lifeMax = 100.0;
    if (sysGetGlobal("server.bots")) {
        new own = teamSize(myTeam);
        new other = teamSize(3 - myTeam);
        if (own > 0 && other > own)
            lifeMax = 100.0 * float(other) / float(own);
        g_1c68 = lifeMax;
    } else {
        lifeMax = g_1c68 > 1.0 ? g_1c68 : 150.0;
    }
    lifeBefore = g_1c68;
    actorSetPropReal("life", g_1c68, 0);
    actorSetPropReal("lifecapacity", lifeMax, 0);      // the spectators' life meter (hud.p @setTelecastPlayer)
    if (sysGetGlobal("server.bots") && botIndex) {
        // a node of its own, as a player (world_map.p names the sub a spectator follows by it): every console
        // learns its name and team (bots_partie.p @botJoin)
        actorSetPropInt("nodeid", BOT_NODE + botIndex, 0);
        netCallPublic(UID_GAME_STATE, "@botJoin", botIndex, myTeam);
    }
    torpedoes = torpedoMax;
    homing = 0;                                         // a player has none: they are picked up
    spawnPlace();
    // its temper: the distance it keeps, how much it presses, its side, its depth
    pRange = 0.85 + frandom() * 0.4;
    pAggro = frandom();
    pSide = frandom() < 0.5 ? -1 : 1;
    pDepth = (frandom() - 0.5) * 500.0;
    flank = (botIndex ? botIndex : me) % 3 - 1;
    predictMode = random(2);
#if SDSW_VERSION >= 5200
    // seen by the others (synced by surface_sub): its repair for the teammates near it (pscope_player
    // func_19744), hidden from the enemies' sonar when hurt (sonar.p func_5d6c)
    actorSetPropInt("teamRepair", crewTeamRepair, 0);
    actorSetPropInt("targetHideSonar", crewHideSonar, 0);
#endif
    yawWant = g_1cc8;
    yawSteer = g_1cc8;
    depthWant = fmin(g_1ca0[1], -300.0);
    stuckAt = g_1ca0;
    // the map, the subs (players, bots, the other consoles' copies) and the players' torpedoes
    actorSetCollisionCheck(COLL_MAP | COLL_TORPEDO | COLL_ITEM | COLL_SUB | COLL_REMOTE, 0);
    floatveczero(vel);
    floatveczero(push);
}

/* Where a player would start: the game puts each player at the spawn point <map>_p<slot> of the map
 * (mode_periscope inputProperties), slot (node index + network.randomstartloc) % 8 + 1, or on the maps
 * whose teams start apart (teamSpawnIndex, func_540c), (randomstartloc + rank in its team) % 4 + 1, + 4 for
 * the second team. The bots take the slots after the players', as more players would. The points come from
 * the map's own files (bxml/sdsw_spawn_<map>_p<slot>: their position and bearing, made by mod.toml). */
spawnPlace()
{
    new stage = sysGetGlobal("player.stage") - 9;      // online stages 10.. are the maps 1..
    if (stage < 1 || stage > 99)
        return;
    new name[64];
    new a = worldNewActor();
    strformat(name, sizeof name, false, "sdsw_spawn_scope00_online_stage%02d", stage);
    if (!actorReadProperties(name, a)) {
        actorKill(a);
        return;
    }
    new teams = 0;
    actorGetPropInt("teamSpawnIndex", teams, a);
    new shift = sysGetGlobal("network.randomstartloc");
    new nodes = netGetNodeCount();
    // its rank among the bots: of its team (j), of all (n)
    new j = 0;
    new n = 0;
    new players1 = playersOf(1);
    new players2 = playersOf(2);
    if (botIndex) {
        // the server's bots: those of the players' team (the one with more players) first, k = 1...
        new playersTeam = players2 > players1 ? 2 : 1;
        new mine = clamp(sysGetGlobal("server.bots.mine") - (playersTeam == 1 ? players1 : players2), 0, 4);
        n = botIndex - 1;
        j = myTeam == playersTeam ? n : n - mine;
    } else {
        // the game's: npcNum 0-2 blue, 3-5 red, a team with players only (mode_periscope @setNpc)
        new npc = 0;
        actorGetPropInt("npcNum", npc, 0);
        j = npc % 3;
        n = myTeam == 1 ? j : (players1 ? max(4 - players1, 0) : 0) + j;
    }
    new slot;
    if (teams)
        slot = (shift + (myTeam == 1 ? players1 : players2) + j) % 4 + 1 + (myTeam == 1 ? 0 : 4);
    else
        slot = (shift + nodes + n) % 8 + 1;
    strformat(name, sizeof name, false, "sdsw_spawn_scope00_online_stage%02d_p%d", stage, slot);
    new Float:p[3] = { 0.0, 1.0, 0.0 };
    new Float:bearing = 0.0;
    if (actorReadProperties(name, a) && actorGetPropVector("spawnPosition", p, a) && p[1] < 1.0) {
        actorGetPropReal("spawnBearing", bearing, a);
        g_1ca0 = p;
        if (g_1ca0[1] > SURFACE - 200.0)
            g_1ca0[1] = SURFACE - 200.0;                // a player's sub starts at the surface; it dives at once
        g_1cc8 = wrapAngle(bearing * PI / 180.0);
        actorSetPosition(g_1ca0, 0);
        actorSetYaw(g_1cc8, 0);
    }
    actorKill(a);
}

/* Players of a team in the battle (player.<node>.team). */
playersOf(team)
{
    new count = 0;
    new name[48];
    new nodes = netGetNodeCount();
    for (new i = 0; i < nodes; i++) {
        strformat(name, sizeof name, false, "player.%x.team", netGetNodeIdFromIdx(i));
        if (sysGetGlobal(name) == team)
            count++;
    }
    return count;
}

/* A team's size in a battle against the server's bots: its players, or the size the server set
 * (server.bots.mine for the players' team, the one with more players; server.bots.other). */
teamSize(team)
{
    new players = sysGetGlobal(team == 1 ? "team.01.players" : "team.02.players");
    new playersTeam = sysGetGlobal("team.02.players") > sysGetGlobal("team.01.players") ? 2 : 1;
    return max(players, sysGetGlobal(team == playersTeam ? "server.bots.mine" : "server.bots.other"));
}

/* A bot of the server is hit as a player is (pscope_player.p @eventDamageTorp, @eventMessageExplosionHit):
 *  - a torpedo does a player's damage: the same as a player's torpedo to a player, 30 for a homing one
 *    (damageToPlayer of bxml/surface_torpedo_p_homing; the game gives a computer sub damageToNpc, 70);
 *  - an explosion does a player's 5 (damageToPlayer of bxml/explosion_damage; a computer sub took 30) within 750
 *    (a computer sub: within 300);
 *  - 60 frames after a hit (and after the start), torpedoes and explosions do nothing (g_c8c0);
 *  - the damage is times the damageRate of its submarine, rounded up;
 *  - no message of the game's computer subs ("L'ennemi a été coulé !": bots_partie.p says what players are
 *    told), and a bot's shot shows no hit on this console's HUD (func_7b8c shows it when the shooter's node is
 *    this console's). */
const Float:HOMING_TO_PLAYER = 30.0;
const Float:EXPLOSION_TO_PLAYER = 5.0;
const Float:EXPLOSION_RANGE = 750.0;

botHit(&Float:damage, &shooter, &fromNpc)
{
    if (collisionHit) {
        collisionHit = 0;                               // a collision: no window (@eventDamage, arg6 = 1)
    } else if (hitWindow || damage <= 0.0) {
        damage = 0.0;
    } else {
        hitWindow = 60;
    }
    damage = float(floatround(damage * damageRate, 2));
    if (fromNpc)
        shooter = -1;
    fromNpc = 1;
}

forward botTorpedoArgs(&Float:damage, &shooter, &sameTeam, &isHoming, &fromNpc);
public botTorpedoArgs(&Float:damage, &shooter, &sameTeam, &isHoming, &fromNpc)
{
    if (!lvl || !sysGetGlobal("server.bots"))
        return 0;
    if (sameTeam && !collisionHit)
        damage = 0.0;                                   // a teammate's torpedo: "Vous avez touché un allié !", no damage
    if (isHoming && !collisionHit)
        damage = HOMING_TO_PLAYER;
    botHit(damage, shooter, fromNpc);
    return 1;
}

forward botExplosionArgs(&Float:damage, &shooter, &sameTeam, &Float:range, &fromNpc);
public botExplosionArgs(&Float:damage, &shooter, &sameTeam, &Float:range, &fromNpc)
{
    if (!lvl || !sysGetGlobal("server.bots"))
        return 0;
    damage = sameTeam ? 0.0 : EXPLOSION_TO_PLAYER;
    range = EXPLOSION_RANGE;
    botHit(damage, shooter, fromNpc);
    return 1;
}

/* A player's sub takes 2.5 when it touches the map or another sub, once a second (pscope_player.p
 * @eventCollide, g_c8c4), whatever its window: as a hit with no shooter. */
collisionDamage()
{
    if (!bumpDamage || collideTime || !sysGetGlobal("server.bots"))
        return;
    bumpDamage = 0;
    collideTime = 60;
    collisionHit = 1;
    torpedoHit(g_1ca0[0], g_1ca0[1], g_1ca0[2], 2.5, 1, 0, 0, 0, -1, 0, 1);
    collisionHit = 0;
}

/* The characteristics of its submarine: server.bots.sub<k> for the server's bots, else the first one. */
readSubmarine()
{
    new k = 0;
    new sub = 1;
    new name[48];
    actorGetPropInt("botIndex", k, 0);
    botIndex = k;
    if (k) {
        strformat(name, sizeof name, false, "server.bots.sub%d", k);
        sub = sysGetGlobal(name);
        if (sub < 1 || sub > 39)                        // 23 in the game, 39 with the update
            sub = 1;
    }
    new a = worldNewActor();
    strformat(name, sizeof name, false, "pscope_ply%02d_stats", sub);
    actorReadProperties(name, a);
    new turnRating = 4;
    new accelRating = 4;
    new diveRating = 4;
    new damageRating = 5;
    actorGetPropInt("damageRate", damageRating, a);
    new replenish = 6;
    actorGetPropInt("maxTurn", turnRating, a);
    actorGetPropInt("belowAccel", accelRating, a);
    actorGetPropInt("diveRate", diveRating, a);
    actorGetPropInt("torpedoLevel", torpedoLevel, a);
    actorGetPropInt("torpedoMax", torpedoMax, a);
    actorGetPropInt("torpedoReplenishTime", replenish, a);
    actorGetPropInt("torpedoFireInterval", fireInterval, a);
    actorGetPropReal("maskerUseAir", maskerCost, a);
    actorGetPropInt("torpedoFireBrakeTime", brakeFrames, a);
    actorGetPropReal("torpedoFireBrakeRate", brakeRate, a);
    actorGetPropReal("diveDrag", diveDrag, a);
    actorGetPropVector("torpedoSpawnPoint", tubeLocal, a);
    crewCount = 1;
    actorGetPropInt("crewCount", crewCount, a);
    // its crew, as a player's (pscope_player.p customUpdateSubBonusStats): each member adds to the ratings
    if (k) {
        strformat(name, sizeof name, false, "server.bots.crew%d", k);
        new packed = sysGetGlobal(name);                // up to 5 members, 6 bits each: member + 1, 0 none
        for (new i = 0; i < 5 && i < crewCount; i++) {
            new member = ((packed >> (6 * i)) & 63) - 1;
            crewMembers[i] = member;
            if (member >= 0)
                addCrew(member, turnRating, accelRating, diveRating, damageRating, replenish);
        }
    }
    turnRating = clamp(turnRating, 1, 10);
    accelRating = clamp(accelRating, 1, 10);
    diveRating = clamp(diveRating, 1, 10);
    damageRating = clamp(damageRating, 1, 10);
    replenish = clamp(replenish, 1, 30);
    actorReadProperties("table_maxturn", a);
    strformat(name, sizeof name, false, "maxTurn_%d", turnRating);
    actorGetPropReal(name, maxTurn, a);
    actorReadProperties("table_below_accel", a);
    strformat(name, sizeof name, false, "belowAccel_%d", accelRating);
    actorGetPropReal(name, accel, a);
    actorReadProperties("table_dive_rate", a);
    strformat(name, sizeof name, false, "diveRate_%d", diveRating);
    actorGetPropReal(name, diveRate, a);
    actorReadProperties("table_damage_rate", a);
    strformat(name, sizeof name, false, "damageRate_%d", damageRating);
    actorGetPropReal(name, damageRate, a);
    actorKill(a);
    damageRate = fclamp(damageRate, 0.5, 2.0);
    if (torpedoLevel < 1 || torpedoLevel > 3)
        torpedoLevel = 1;
    if (torpedoMax < 1)
        torpedoMax = 6;
    replenishFrames = 30 * (replenish > 0 ? replenish : 6);
    if (fireInterval < 30)
        fireInterval = 85;
    if (maskerCost <= 0.0)
        maskerCost = 33.3;
    maxTurn = fclamp(maxTurn, 0.01, 0.09);
    accel = fclamp(accel, 0.3, 0.54);
    diveRate = fclamp(diveRate, 0.25, 0.7);
    diveDrag = fclamp(diveDrag, 0.1, 0.3);
    brakeRate = fclamp(brakeRate, 0.9, 1.0);
    g_1c78 = accel / LIN_DRAG;
}

/* A member of the crew (worlds/crew_stats: the actors crew_NN the player's script loads, pscope_player.p
 * func_47b0): its ratings, and its ability. */
addCrew(member, &turnRating, &accelRating, &diveRating, &damageRating, &replenish)
{
    new name[16];
    strformat(name, sizeof name, false, "crew_%02d", member);
    new c = worldFindActor(name);
    if (!c) {
        worldLoad("crew_stats", 255);
        c = worldFindActor(name);
        if (!c)
            return;
    }
    turnRating += crewValue("maxTurn", c);
    accelRating += crewValue("belowAccel", c);
    diveRating += crewValue("diveRate", c);
    damageRating += crewValue("damageRate", c);
    torpedoMax += crewValue("torpedoMax", c);
    replenish += crewValue("torpedoReplenishTime", c);
    if (crewValue("lockOnLong", c))
        seeRange = 8500.0;                              // player_label.p func_32fc: 8500 instead of 7000
    if (crewValue("wideSonar", c))
        sonarRange = 20000.0;                           // sonar.p func_42d4: 20000 instead of 15000
    if (crewValue("maskerConsumptionRate", c))
        maskerCost = 25.0;                              // periscope_move.p maskerActivate: 25 of air
    crewRepair |= crewValue("repair", c);
#if SDSW_VERSION >= 5200
    crewLongMasker |= crewValue("longMasker", c);      // 450 frames instead of 300
    crewAirUp |= crewValue("airRepairUp", c);          // 0.3 of air a frame at the surface instead of 0.2
    crewAutoMasker |= crewValue("autoMasker", c);      // on when a homing torpedo locks on it
    crewTeamRepair |= crewValue("teamRepair", c);      // repairs its teammates within 2000
    crewHideSonar |= crewValue("hideSonar", c);        // not on the enemies' sonar under 40 of hull
#endif
}

crewValue(const property[], c)
{
    new v = 0;
    actorGetPropInt(property, v, c);
    return v;
}

timers()
{
    if (reload)
        reload--;
    // as a player: the torpedoes come back all at once, torpedoReplenishTime after the last one was fired
    // (periscope_move.p: only while there is none left)
    if (!torpedoes && ++emptyFor >= replenishFrames) {
        torpedoes = torpedoMax;
        emptyFor = 0;
    }
    if (homingIn)
        homingIn--;
    if (maskerIn)
        maskerIn--;
    if (sonarIn)
        sonarIn--;
    if (bumpTime)
        bumpTime--;
    if (hitWindow)
        hitWindow--;
    if (collideTime)
        collideTime--;
    if (hurtTime)
        hurtTime--;
    if (evadeTime)
        evadeTime--;
    if (backOutTime)
        backOutTime--;
    if (maskerTime && --maskerTime == 0)
        maskerOff();
    if (maskerTime && frame - autoMaskerAt == 90 && g_1c68 >= lifeMax * 0.4)
        maskerOff();                                    // the homing torpedo lost it: back to the fight
    if (g_1ca0[1] > -30.0 && air < 100.0)
        air = fmin(air + (crewAirUp ? 0.3 : 0.2), 100.0);   // as a player: air comes back at the surface only
    // repair (crew): a hundredth of its hull every 75 frames (v0 pscope_player func_14ca8; v5200 func_1a248:
    // every 60), or a teammate's repair within 2000 (v5200 func_1a424: every 75)
#if SDSW_VERSION >= 5200
    new Float:repair = crewRepair ? 60.0 : (mateRepairs ? 75.0 : 0.0);
#else
    new Float:repair = crewRepair ? 75.0 : 0.0;
#endif
    if (repair > 0.0 && g_1c68 < lifeMax) {
        g_1c68 = fmin(g_1c68 + lifeMax / 100.0 / repair, lifeMax);
        lifeBefore = g_1c68;
    }
    if (g_1c68 < lifeBefore - 0.5)
        hurtTime = 120;
    // hit: seen a moment through its masker, as a player (pscope_player.p func_a758: custom flag 6, which
    // func_60b4 flashes; the other consoles' copies do it from the life they are sent)
    actorSetCustomFlag(6, g_1c68 < lifeBefore, 0);
    lifeBefore = g_1c68;
}

/* ---- seeing ------------------------------------------------------------------------------------- */

/* Nothing of the map between here and there. */
bool:clearLine(const Float:from[3], const Float:to[3], Float:margin)
{
    new Float:d[3];
    floatvecsubto(d, to, from);
    new Float:length = floatveclength(d);
    if (length < 1.0)
        return true;
    floatvecscale(d, 1.0 / length);
    return worldClipLine(from, d, length, COLL_MAP) >= length - margin;
}

isMasked(actor)
{
    if (actorGetCustomFlag(6, actor)) {
        revealed = actor;                               // hit under its masker: it shows for a moment
        revealedAt = frame;
    }
    if (actor == revealed && frame - revealedAt < 20)
        return 0;
    new on = 0;
    new masker = 0;
    actorGetPropInt("masker_on", on, actor);
    actorGetPropInt("masker", masker, actor);
    return on || masker;
}

/* What a player sees (player_label.p func_32fc, func_305c): an enemy within 7000 with nothing of the map in
 * between, not under its masker; or one its sonar found less than 300 frames ago, within 15000 (setSonarTime).
 * Nothing else: no seeing through walls, no map of every sub. */
const SONAR_SHOWS = 300;             // frames a sonar contact shows (player_label.p @setSonarTime)
const SONAR_EVERY = 120;             // frames between two pings (sonar.p func_414c)


isContact(actor)
{
    if (frame - contactAt >= SONAR_SHOWS)
        return 0;
    for (new i = 0; i < contactCount; i++)
        if (contacts[i] == actor)
            return 1;
    return 0;
}

/* A ping, as a player's (sonar.p func_414c, func_42d4): the subs within 15000, but not a sub of another
 * console that is stopped (throttle under 0.05: the sonar does not hear it); every console sees the ping
 * on its sonar (last_sonar, synced; this console's sonar is told here). */
ping()
{
    sonarIn = SONAR_EVERY;
    new pings = 0;
    actorGetPropInt("last_sonar", pings, 0);
    actorSetPropInt("last_sonar", pings + 1, 0);
    sysCallPublic(UID_SONAR, "@addFound", me);
    sysCallPublic(UID_PLAYER_LABEL, "@setSonarTime", me);
    new found[16];
    new count = worldFindActors(found, g_1ca0, sonarRange, COLL_SUB | COLL_REMOTE, sizeof found);
    contactCount = 0;
    for (new i = 0; i < count && contactCount < sizeof contacts; i++) {
        new a = found[i];
        if (a == me)
            continue;
        new Float:throttleOf = 1.0;
        if (actorGetCollisionType(a) & COLL_REMOTE && actorGetPropReal("throttle", throttleOf, a)
            && fabs(throttleOf) < 0.05)
            continue;
#if SDSW_VERSION >= 5200
        // hideSonar: an enemy under 40 of hull does not show (sonar.p func_5d6c)
        new hides = 0;
        new Float:life = 100.0;
        new team = 0;
        if (actorGetPropInt("targetHideSonar", hides, a) && hides == 1 && actorGetPropReal("life", life, a)
            && life <= 40.0 && actorGetPropInt("teamColor", team, a) && team != myTeam)
            continue;
#endif
        contacts[contactCount++] = a;
    }
    contactAt = frame;
}

/* The enemies it sees or its sonar found, the teammates, the containers, and the torpedoes coming. */
lookAround()
{
    new found[16];
    new count = worldFindActors(found, g_1ca0, sonarRange, COLL_SUB | COLL_REMOTE, sizeof found);
    new best = -1;
#if SDSW_VERSION >= 5200
    mateRepairs = 0;
#endif
    new Float:bestScore = 1000000.0;
    new heard = -1;
    new Float:heardDistance = 1000000.0;
    mateCount = 0;
    for (new i = 0; i < count; i++) {
        new a = found[i];
        if (a == me)
            continue;
        new team = 0;
        actorGetPropInt("teamColor", team, a);
        if (!team)
            continue;
        new Float:life = 1.0;
        actorGetPropReal("life", life, a);
        if (life <= 0.01)
            continue;
        if (team == myTeam) {
            if (mateCount < sizeof mates)
                mates[mateCount++] = a;
#if SDSW_VERSION >= 5200
            new repairs = 0;
            new Float:mp[3];
            if (actorGetPropInt("teamRepair", repairs, a) && repairs && actorGetPosition(mp, a)
                && distance(mp, g_1ca0) <= 2000.0)
                mateRepairs = 1;
#endif
            continue;
        }
        new Float:p[3];
        actorGetPosition(p, a);
        new Float:d = distance(p, g_1ca0);
        new contact = isContact(a);
        if (contact && d < heardDistance) {
            heard = a;                                  // on its sonar, masked or not: where to go
            heardDistance = d;
        }
        if (isMasked(a))
            continue;                                   // under its masker it cannot be aimed at
        new bool:seen = d <= seeRange && clearLine(g_1ca0, p, 200.0);
        if (!seen && !contact)
            continue;
        // the nearest, the weakest, the one it can shoot at; it keeps its target unless another is much better
        new Float:score = d + life * 12.0 + (seen ? 0.0 : 2500.0);
        if (a == target)
            score = score * 0.7 - 400.0;
        if (score < bestScore) {
            bestScore = score;
            best = a;
        }
    }
    if (best != target) {
        target = best;
        targetSince = frame;
        tHistoryCount = 0;
        floatveczero(tVel);
        tOmega = 0.0;
        tTurning = 0;
        tSwerve = -1000;
    }
    if (target == -1 && heard != -1) {
        actorGetPosition(goal, heard);                  // where its sonar heard one
        goalValid = 1;
    }
    // no one to fight: a ping now and then, as a player looking for the others
    if (target == -1 && !sonarIn && frandom() < 0.25)
        ping();
    lookForContainers();
    watchTorpedoes();
}

/* The containers the sunk subs leave (surface_item, type 0x100): a player picks them up, the game's
 * computer subs cannot (surface_item.p @eventCollide). One in sight it goes for when it needs it. */
lookForContainers()
{
    new found[6];
    new count = worldFindActors(found, g_1ca0, 4000.0, COLL_ITEM, sizeof found);
    container = -1;
    new Float:best = 1000000.0;
    for (new i = 0; i < count; i++) {
        new kind = 0;
        actorGetPropInt("itemNum", kind, found[i]);
        if (kind == 1 ? homing >= 3 : g_1c68 > lifeMax - 1.0)
            continue;                                   // homing torpedoes: 3 at most; repair: not needed
        new Float:p[3];
        actorGetPosition(p, found[i]);
        new Float:d = distance(p, g_1ca0);
        if (d < best && clearLine(g_1ca0, p, 150.0)) {
            best = d;
            container = found[i];
        }
    }
}

/* A torpedo that will pass close: change depth and turn across its path. */
watchTorpedoes()
{
    if (evadeTime)
        return;
    new found[8];
    new count = worldFindActors(found, g_1ca0, 3500.0, COLL_TORPEDO | COLL_TORPEDO_NPC, sizeof found);
    for (new i = 0; i < count; i++) {
        new t = found[i];
        new shooter = 0;
        actorGetPropInt("actor_id", shooter, t);
        if (shooter == me)
            continue;
        new team = 0;
        actorGetPropInt("teamColor", team, t);
        if (team && team == myTeam)
            continue;
        new Float:p[3];
        new Float:v[3];
        actorGetPosition(p, t);
        actorGetVelocity(v, t);
        new Float:speed2 = floatvecdot(v, v);
        if (speed2 < 25.0)
            continue;
        new Float:r[3];
        floatvecsubto(r, g_1ca0, p);
        new Float:when = floatvecdot(r, v) / speed2;           // frames to the closest point
        if (when <= 0.0 || when > 75.0)
            continue;
        floatvecaddscale(r, v, -when);                       // where it passes, from me
        if (floatveclength(r) > 260.0)
            continue;
        new homingShot = 0;
        actorGetPropInt("p_homing", homingShot, t);
        if (homingShot && crewAutoMasker && when < 60.0)
            homingLocked();                             // a homing torpedo on its way: its crew masks it
        if (frandom() > DODGE[lvl])
            continue;
        evadeTime = 35 + random(30);
        // away from its path or across it, either side, and up or down (a torpedo keeps its depth), at full
        // speed or braking hard to let it pass ahead: never the same way twice
        if (floatveclength(r) > 60.0 && frandom() < 0.7)
            evadeYaw = wrapAngle(yawOf(r) + (frandom() - 0.5) * 0.6);
        else
            evadeYaw = wrapAngle(yawOf(v) + (frandom() > 0.5 ? 1.5708 : -1.5708));
        evadeThrottle = frandom() < 0.75 ? 1.0 : -1.0;
        new Float:shift = 200.0 + frandom() * 150.0;
        depthWant = g_1ca0[1] + ((g_1ca0[1] > p[1]) == (frandom() < 0.75) ? shift : -shift);
        return;
    }
}

/* The target, every frame: where it is, how fast it goes and turns (over the last 8 frames). */
follow()
{
    if (target == -1)
        return;
    new Float:p[3];
    new Float:life = 1.0;
    // gone, sunk, or its actor reused by something else
    if (!(actorGetCollisionType(target) & (COLL_SUB | COLL_REMOTE)) || !actorGetPosition(p, target)
        || (actorGetPropReal("life", life, target) && life <= 0.01)) {
        target = -1;
        return;
    }
    if (isMasked(target)) {
        // vanished under its masker: it only knows where it was going
        target = -1;
        lostAt = frame;
        lostPos = tPos;
        lostVel = tVel;
        blindShots = 0;
        return;
    }
    tPos = p;
    tHead = (tHead + 1) % 8;                            // ring of the last 8 positions
    tHistory[tHead * 3] = p[0];
    tHistory[tHead * 3 + 1] = p[1];
    tHistory[tHead * 3 + 2] = p[2];
    if (tHistoryCount < 8)
        tHistoryCount++;
    if (tHistoryCount >= 2) {
        new last = (tHead + 9 - tHistoryCount) % 8;     // the oldest
        new Float:span = float(tHistoryCount - 1);
        new Float:v[3];
        v[0] = (p[0] - tHistory[last * 3]) / span;
        v[1] = (p[1] - tHistory[last * 3 + 1]) / span;
        v[2] = (p[2] - tHistory[last * 3 + 2]) / span;
        new Float:heading = yawOf(v);
        new Float:flat = floatsqroot(v[0] * v[0] + v[2] * v[2]);
        if (flat > 2.0 && tHistoryCount >= 8) {
            tOmega = tOmega * 0.8 + fclamp(wrapAngle(heading - tHeading), -0.08, 0.08) * 0.2;
            new turning = tOmega > 0.005 ? 1 : (tOmega < -0.005 ? -1 : 0);
            if (turning && turning != tTurning) {
                if (tTurning)
                    tSwerve = frame;
                tTurning = turning;
            }
        } else
            tOmega = tOmega * 0.9;
        tHeading = heading;
        tVel = v;
    }
    if (frame % 15 == 0 || frame - targetSince < 2)
        tVisible = _:clearLine(g_1ca0, p, 200.0);
    lastKnown = p;
    lastKnownTime = frame;
    learn();
}

/* How its target dodges: the turn it takes 30 frames after a shot (a human sees it and reacts), averaged over
 * the shots, kept per player for the session (bots.dodge.<node>: every bot of this console learns from the
 * others), so that a habit of always breaking the same way gets punished. */
learn()
{
    if (!LEARNS[lvl])
        return;
    new node = 0;
    if (learnOf != target) {
        learnOf = target;
        learnCount = 0;
        learnOmega = 0.0;
        watchShot = -1;
        if (actorGetPropInt("nodeid", node, target) && node) {
            new name[32];
            strformat(name, sizeof name, false, "bots.dodgen.%x", node);
            learnCount = sysGetGlobal(name);
            strformat(name, sizeof name, false, "bots.dodge.%x", node);
            learnOmega = Float:sysGetGlobal(name);
        }
    }
    if (watchShot < 0 || frame - watchShot < 30)
        return;
    watchShot = -1;
    new Float:omega = fclamp(tOmega, -0.05, 0.05);
    learnOmega = learnCount ? learnOmega * 0.7 + omega * 0.3 : omega;
    learnCount = min(learnCount + 1, 50);
    if (actorGetPropInt("nodeid", node, target) && node) {
        new name[32];
        strformat(name, sizeof name, false, "bots.dodgen.%x", node);
        sysSetGlobal(name, learnCount);
        strformat(name, sizeof name, false, "bots.dodge.%x", node);
        sysSetGlobal(name, _:learnOmega);
    }
}

/* ---- deciding ----------------------------------------------------------------------------------- */

decide()
{
    new Float:health = g_1c68 / lifeMax;
    throttleWant = 0.8;
    climbWant = NO_CLIMB;
    if (target == -1 && frame - lostAt < 240) {
        guess();
        return;
    }
    if (container != -1 && (target == -1 || (health < 0.5 && distance(tPos, g_1ca0) > 3000.0))) {
        new Float:p[3];
        actorGetPosition(p, container);
        new Float:to[3];
        floatvecsubto(to, p, g_1ca0);
        yawWant = yawOf(to);
        depthWant = p[1];
        throttleWant = 1.0;
        if (evadeTime) {
            yawWant = evadeYaw;
        }
        return;
    }
    if (target == -1) {
        wander();
        if (evadeTime) {
            yawWant = evadeYaw;
            throttleWant = evadeThrottle;
        }
        return;
    }
    new Float:toTarget[3];
    floatvecsubto(toTarget, tPos, g_1ca0);
    new Float:d = floatveclength(toTarget);
    new Float:aim[3];
    new Float:aimPoint[3];
    new Float:aimYaw = yawOf(toTarget);
    if (frame % 3 == 0 || frame - targetSince < 3)
        aimFlight = intercept(aimDir, aimAt);           // every 3 frames to steer, again before a shot
    new flight = aimFlight;
    aim = aimDir;
    aimPoint = aimAt;
    if (flight)
        aimYaw = yawOf(aim);
    new Float:range = torpedoRange();
    // an agile target is only hit from close: the shorter the torpedo's run, the less it can turn away; each
    // bot keeps a distance of its own (its temper)
    new Float:wanted = (agile() ? 1700.0 : fclamp(range * 0.35, 2200.0, 3000.0)) * pRange;
    new ready = !reload && !maskerTime && flight && (torpedoes || (homing && !homingIn));

    if (health < 0.4) {
        // it backs away still firing; under its masker only when the enemy closes in or hits it again
        if (!maskerTime && !maskerIn && air >= maskerCost && (d < 1800.0 || (hurtTime && d < 3500.0)))
            maskerOn();
        if (maskerTime) {
            // hidden: away from it, full speed, deep
            yawWant = wrapAngle(yawOf(toTarget) + PI);
            throttleWant = 1.0;
            depthWant = fmin(g_1ca0[1], floorY + 250.0);
            return;
        }
        // still firing, backing away
        yawWant = aimYaw;
        throttleWant = d < range * 0.8 ? -1.0 : 0.2;
    } else if (!tVisible) {
        yawWant = yawOf(toTarget);                      // round the obstacle (steerClear) to see it
        throttleWant = 1.0;
    } else if (d > wanted + 700.0 + 700.0 * (1.0 - pAggro)) {
        // closing in; from its own side when teammates fight the same target
        yawWant = d > 3500.0 && mateCount ? wrapAngle(aimYaw + 0.45 * float(flank)) : aimYaw;
        throttleWant = 1.0;
    } else if (d < wanted - 1000.0) {
        yawWant = aimYaw;                               // too close: back off, facing it
        throttleWant = -1.0;
    } else {
        combat(toTarget, d, wanted, aimYaw, ready);
    }
    if (evadeTime) {
        yawWant = evadeYaw;
        throttleWant = evadeThrottle;
    } else {
        // a torpedo leaves along the sub, whose nose goes down as it dives (pitch -> -0.1 * vertical speed,
        // pscope_player.p func_12184): dive or climb at the speed that points it at the target, which also
        // brings it to the target's depth; between two shots, another depth now and then
        depthWant = tPos[1] + tVel[1] * 30.0 + (ready ? 0.0 : depthShift);
        if (flight && fabs(aim[1]) < 0.5 && ready)
            climbWant = fclamp(10.0 * aim[1], -diveRate / diveDrag, diveRate / diveDrag);
    }
    if (d < 900.0 && throttleWant > 0.0)
        throttleWant = -1.0;                            // never ram it
    fire(aim, aimPoint, d, flight);
}

/* In range of its target: the maneuver of the moment, changed every few seconds at random (weighted by its
 * temper), as a player does not fly the same way twice. Ready to fire and nearly facing it, it turns in. */
combat(const Float:toTarget[3], Float:d, Float:wanted, Float:aimYaw, ready)
{
    if (frame >= maneuverUntil)
        pickManeuver();
    new Float:facing = fabs(wrapAngle(aimYaw - g_1cc8));
    if (ready && (facing < 0.35 || maneuver == M_HOLD || maneuver == M_CLOSE || maneuver == M_STOP)) {
        yawWant = aimYaw;
        throttleWant = maneuver == M_STOP ? 0.0 : (maneuver == M_CLOSE && d > wanted * 0.75 ? 0.9 : maneuverThrottle);
        return;
    }
    new Float:bearing = yawOf(toTarget);
    if (maneuver == M_CIRCLE) {
        // across its line, a little inward or outward to keep the distance
        new Float:keep = fclamp((d - wanted) / 1500.0, -0.4, 0.4);
        yawWant = wrapAngle(bearing + float(pSide) * (1.35 - keep));
        throttleWant = 0.9;
    } else if (maneuver == M_CLOSE) {
        yawWant = aimYaw;
        throttleWant = d > wanted * 0.75 ? 0.9 : 0.3;
    } else if (maneuver == M_BREAK) {
        yawWant = wrapAngle(bearing + PI - float(pSide) * 0.7);
        throttleWant = 1.0;
    } else if (maneuver == M_STOP) {
        yawWant = aimYaw;
        throttleWant = 0.0;
    } else {
        yawWant = aimYaw;
        throttleWant = maneuverThrottle;
    }
}

pickManeuver()
{
    new r = random(100);
    new Float:aggro = pAggro;
    if (lvl == 1) {
        maneuver = r < 60 ? M_HOLD : (r < 85 ? M_CIRCLE : M_DEPTH);
    } else {
        // an aggressive bot closes in and stops short more, a careful one circles and breaks off
        new hold = 18;
        new circle = hold + 30 - floatround(10.0 * aggro);
        new close = circle + 10 + floatround(15.0 * aggro);
        new brk = close + 14 - floatround(8.0 * aggro);
        new depth = brk + 14;
        maneuver = r < hold ? M_HOLD : (r < circle ? M_CIRCLE : (r < close ? M_CLOSE : (r < brk ? M_BREAK
                   : (r < depth ? M_DEPTH : M_STOP))));
    }
    new frames = MANEUVER_MIN[lvl] + random(MANEUVER_SPAN[lvl]);
    if (maneuver == M_BREAK || maneuver == M_STOP)
        frames = frames / 2;
    maneuverUntil = frame + frames;
    maneuverThrottle = 0.2 + frandom() * 0.6;
    if (maneuver == M_CIRCLE && frandom() < 0.45)
        pSide = -pSide;
    depthShift = maneuver == M_DEPTH ? (frandom() < 0.5 ? -1.0 : 1.0) * (200.0 + frandom() * 350.0) : pDepth * 0.4;
}

/* Its target vanished under its masker: it goes where the target was heading (as far as 2 s of it), and may
 * fire one or two torpedoes there at a guess. It does not see it. */
guess()
{
    new Float:lost = float(min(frame - lostAt, 60));
    new Float:p[3];
    p = lostPos;
    floatvecaddscale(p, lostVel, lost);
    new Float:to[3];
    floatvecsubto(to, p, g_1ca0);
    yawWant = yawOf(to);
    depthWant = p[1];
    throttleWant = floatveclength(to) > 1500.0 ? 0.8 : 0.3;
    if (evadeTime) {
        yawWant = evadeYaw;
        throttleWant = evadeThrottle;
    }
    if (blindShots >= 2 || !torpedoes || torpedoes < torpedoMax / 2 || reload || frandom() > 0.05)
        return;
    // a shot at a guess: where it would be if it went on, with the same aim as a seen target
    new Float:keepPos[3];
    new Float:keepVel[3];
    keepPos = tPos;
    keepVel = tVel;
    new Float:keepOmega = iOmega;
    new Float:keepOmega2 = iOmega2;
    tPos = p;
    tVel = lostVel;
    iOmega = 0.0;
    iOmega2 = 0.0;
    new frames = 0;
    new Float:miss = missNow(frames);
    if (miss < 120.0 && frames >= 8) {
        new Float:tube[3];
        tubePosition(tube);
        if (clearLine(tube, p, 120.0) && !mateInTheWay(tube, p)) {
            new name[32];
            strformat(name, sizeof name, false, "surface_torpedo_lv%02d", torpedoLevel);
            launch(tube, name);
            actorSetPropReal("bearing", g_1cc8, lastTorpedo);
            torpedoes--;
            reload = fireInterval + 15 + FIRE_PAUSE[lvl];   // a player: torpedo.interval + 15 (func_10e04)
            homingIn = 135;
            brakeTime = brakeFrames;
            brake = 1.0;
            side = -side;
            blindShots++;
        }
    }
    tPos = keepPos;
    tVel = keepVel;
    iOmega = keepOmega;
    iOmega2 = keepOmega2;
}

/* Without a target: where the battle is, or around. */
wander()
{
    if (hurtTime && g_1c80[2] != 0.0) {
        // hit by something it does not see: turn to where the hit came from
        new Float:from[3];
        actorLocalVectorToWorld(from, g_1c80, 0);
        yawWant = yawOf(from);
        throttleWant = 0.6;
        return;
    }
    if (lastKnownTime && frame - lastKnownTime < 600 && distance2D(lastKnown, g_1ca0) > 600.0) {
        new Float:d[3];
        floatvecsubto(d, lastKnown, g_1ca0);
        yawWant = yawOf(d);
        depthWant = lastKnown[1];
        throttleWant = 1.0;
        return;
    }
    if (goalValid && distance2D(goal, g_1ca0) > 1500.0) {
        new Float:d[3];
        floatvecsubto(d, goal, g_1ca0);
        yawWant = yawOf(d);
        depthWant = goal[1];
        throttleWant = 1.0;
        return;
    }
    if (distance2D(g_1ca0, wanderTo) < 1500.0 || frame % 900 == 0) {
        // nothing heard: somewhere around the middle of the map
        wanderTo[0] = (frandom() - 0.5) * 12000.0;
        wanderTo[2] = (frandom() - 0.5) * 12000.0;
    }
    new Float:to[3];
    floatvecsubto(to, wanderTo, g_1ca0);
    to[1] = 0.0;
    yawWant = yawOf(to);
    depthWant = fmax(floorY + 300.0, -600.0);
    throttleWant = 0.6;
}

/* A target that changed the way it turns lately (zigzags): aim at it only from close. A steady turn is
 * predicted (intercept). */
agile()
{
    return frame - tSwerve < 120;
}

Float:torpedoRange()
{
    return torpedoLevel == 1 ? 6500.0 : (torpedoLevel == 2 ? 8500.0 : 10000.0);
}

/* How far a torpedo has gone n frames after it starts (from rest: speed = speed * 0.99, position += speed,
 * speed += 1.2, every frame): 118.8 * (n - 100 * (1 - 0.99^n)). */
Float:torpedoRun(Float:n)
{
    return 0.99 * (TORPEDO_ACCEL / (1.0 - TORPEDO_KEEP))
           * (n - (1.0 - floatpower(TORPEDO_KEEP, n)) / (1.0 - TORPEDO_KEEP));
}

/* Where the target will be in n frames: it keeps its speed, and turns at iOmega (a steady turn is a circle),
 * then at iOmega2 after iReact frames (how it dodges, mode 2). */
targetAt(Float:n, Float:p[3])
{
    new Float:t = n + 2.0;                              // the torpedo starts moving a frame or two later
    p = tPos;
    new Float:speed = floatsqroot(tVel[0] * tVel[0] + tVel[2] * tVel[2]);
    new Float:h = tHeading;
    arc(p, h, speed, iOmega, fmin(t, iReact));
    if (t > iReact)
        arc(p, h, speed, iOmega2, t - iReact);
    p[1] = p[1] + tVel[1] * fmin(t, 25.0);              // a dive does not last: no further than 25 frames
    if (p[1] > SURFACE)
        p[1] = SURFACE;
}

/* t frames at this speed, turning at omega from heading h (forward: sin h, cos h). */
arc(Float:p[3], &Float:h, Float:speed, Float:omega, Float:t)
{
    if (fabs(omega) < 0.0002) {
        p[0] = p[0] + floatsin(h, 0) * speed * t;
        p[2] = p[2] + floatcos(h, 0) * speed * t;
        return;
    }
    new Float:r = speed / omega;
    new Float:h2 = h + omega * t;
    p[0] = p[0] + r * (floatcos(h, 0) - floatcos(h2, 0));
    p[2] = p[2] + r * (floatsin(h2, 0) - floatsin(h, 0));
    h = h2;
}

/* Where to shoot so the torpedo meets the target: the run of the torpedo equals the distance to where the
 * target will be (bisection on the time). aim: unit direction from the tube; returns the frames of the run,
 * 0 if out of range. */
intercept(Float:aim[3], Float:point[3])
{
    new Float:tube[3];
    tubePosition(tube);
    // how it leads the shot (predictMode, drawn after each shot): the target keeps turning, goes straight, or
    // turns the way it dodged the last shots, after a human's reaction (15 frames)
    iOmega = 0.0;
    iOmega2 = 0.0;
    iReact = 1000.0;
    if (lvl >= 2 && predictMode != 1) {
        iOmega = tOmega;
        iOmega2 = tOmega;
        if (predictMode == 2 && learnCount >= 2) {
            iOmega2 = learnOmega;
            iReact = 15.0;
        }
    }
    new Float:low = 0.0;
    new Float:high = 240.0;
    new Float:p[3];
    aimAhead(high, tube, p);
    if (torpedoRun(high) < distance(p, tube))
        return 0;
    for (new k = 0; k < 12; k++) {
        new Float:mid = (low + high) * 0.5;
        aimAhead(mid, tube, p);
        if (torpedoRun(mid) < distance(p, tube))
            low = mid;
        else
            high = mid;
    }
    aimAhead(high, tube, p);
    if (torpedoRun(high) > torpedoRange())
        return 0;
    floatvecsubto(aim, p, tube);
    floatvecnormalize(aim, aim);
    targetAt(high, point);
    return floatround(high, 2) + 1;                  // 2: rounded up
}

/* The torpedo keeps the sub's velocity when it leaves (periscope_move.p func_fbdc), slowed as its own:
 * 99 * (1 - 0.99^n) times it in n frames. Where to point so that, with that drift, it meets the target. */
Float:drift(Float:n)
{
    return TORPEDO_KEEP / (1.0 - TORPEDO_KEEP) * (1.0 - floatpower(TORPEDO_KEEP, n));
}

aimAhead(Float:n, const Float:tube[3], Float:p[3])
{
    targetAt(n, p);
    floatvecaddscale(p, vel, -drift(n));
    #pragma unused tube
}

/* Where a torpedo fired now, along the sub's own axis (its rotation) and with its velocity, passes the
 * target: the miss distance at the moment it overtakes it. 100000.0 if it never gets there. */
Float:missNow(&frames)
{
    new Float:tube[3];
    tubePosition(tube);
    new Float:axis[3];
    actorGetAxis(2, axis, 0);
    new Float:low = 0.0;
    new Float:high = 240.0;
    new Float:p[3];
    new Float:t[3];
    torpedoAt(high, tube, axis, t);
    targetAt(high, p);
    floatvecsub(p, t);
    if (floatvecdot(p, axis) > 0.0)
        return 100000.0;                                // still ahead of it at the end of its run
    for (new k = 0; k < 12; k++) {
        new Float:mid = (low + high) * 0.5;
        torpedoAt(mid, tube, axis, t);
        targetAt(mid, p);
        floatvecsub(p, t);
        if (floatvecdot(p, axis) > 0.0)
            low = mid;
        else
            high = mid;
    }
    torpedoAt(high, tube, axis, t);
    targetAt(high, p);
    frames = floatround(high, 2);
    if (torpedoRun(high) > torpedoRange())
        return 100000.0;
    return distance(p, t);
}

torpedoAt(Float:n, const Float:tube[3], const Float:axis[3], Float:t[3])
{
    t = tube;
    floatvecaddscale(t, axis, torpedoRun(n));
    floatvecaddscale(t, vel, drift(n));
}

/* The tube of the next torpedo: torpedoSpawnPoint of the submarine, left and right in turn. */
tubePosition(Float:tube[3])
{
    new Float:local[3];
    floatvecset(local, tubeLocal[0] * float(side), tubeLocal[1], tubeLocal[2]);
    actorLocalPosToWorld(tube, local, 0);
}

/* ---- firing ------------------------------------------------------------------------------------- */

fire(Float:aim[3], Float:point[3], Float:d, flight)
{
    #pragma unused aim
    holdReason = 1;
    if (reload || maskerTime || sysGetGlobal("mode.gameover") || sysGetGlobal("player.timeOver"))
        return;
    holdReason = 2;
    if (!torpedoes && (!homing || homingIn))
        return;
    holdReason = 3;
    if (frame - targetSince < 20 || !tVisible || !flight)
        return;
    holdReason = 4;
    if (lvl >= 2 && agile() && flight > 60 && d > 1600.0)
        return;                                         // it would turn away: closer first
    // a torpedo leaves along the sub's axis, as a player's: the sub must point where it hits
    new frames = 0;
    holdReason = 5;
    if (fabs(wrapAngle(yawOf(aimDir) - g_1cc8)) > 0.05)
        return;                                         // not pointing near it yet (cheap test first)
    new Float:miss = missNow(frames);
    lastMiss = miss;
    if (miss > MISS_ALLOWED[lvl] || frames < 8)
        return;
    holdReason = 6;
    new Float:tube[3];
    tubePosition(tube);
    if (!clearLine(tube, point, 120.0))
        return;
    if (mateInTheWay(tube, point))
        return;
    holdReason = 0;
    // homing: at a target that turns hard or crosses fast, or when hurt
    new Float:yaw = g_1cc8;
    new Float:across = floatsqroot(tVel[0] * tVel[0] + tVel[2] * tVel[2]) * floatsin(fabs(wrapAngle(tHeading - yaw)), 0);
    if (homing && !homingIn && frame - targetSince > 45 && !isMasked(target) && d > 1200.0 && d < 5500.0
        && (fabs(tOmega) > 0.012 || across > 6.0 || g_1c68 < lifeMax * 0.4 || !torpedoes)) {
        launch(tube, "surface_torpedo_p_homing");
        sysCallPublic(UID:lastTorpedo, "@lockOnTarget", target);
        actorSetPropInt("p_homing", 1, lastTorpedo);
        homing--;
    } else if (torpedoes) {
        new name[32];
        strformat(name, sizeof name, false, "surface_torpedo_lv%02d", torpedoLevel);
        launch(tube, name);
        actorSetPropReal("bearing", yaw, lastTorpedo);
        torpedoes--;
        // how will it dodge this one? (the turn it takes 30 frames from now: follow)
        if (LEARNS[lvl] && watchShot < 0)
            watchShot = frame;
    } else {
        return;
    }
    // the next shot is led another way, at random: the target cannot learn one way of dodging
    new r = random(100);
    if (lvl < 2)
        predictMode = 1;
    else if (learnCount >= 2 && LEARNS[lvl])
        predictMode = r < 40 ? 2 : (r < 75 ? 0 : 1);
    else
        predictMode = r < 65 ? 0 : 1;
    reload = fireInterval + 15 + FIRE_PAUSE[lvl] + random(1 + FIRE_PAUSE[lvl] / 2);
    homingIn = 135;                                     // a player's weapons wait 120 + 15 frames after a shot
    brakeTime = brakeFrames;                            // a player's sub brakes when it fires
    brake = 1.0;
    side = -side;
}

/* A teammate near the line of fire. */
mateInTheWay(const Float:from[3], const Float:to[3])
{
    new Float:line[3];
    floatvecsubto(line, to, from);
    new Float:length = floatveclength(line);
    if (length < 1.0)
        return 0;
    floatvecscale(line, 1.0 / length);
    for (new i = 0; i < mateCount; i++) {
        new Float:p[3];
        if (!actorGetPosition(p, mates[i]))
            continue;
        new Float:r[3];
        floatvecsubto(r, p, from);
        new Float:along = floatvecdot(r, line);
        if (along < -100.0 || along > length + 200.0)
            continue;
        floatvecaddscale(r, line, -along);
        if (floatveclength(r) < 220.0)
            return 1;
    }
    return 0;
}

/* A new actor of these properties at this place (surface_sub.p spawnActor without the replays). */
spawn(const properties[], const Float:position[3])
{
    new a = worldNewActor();
    actorReadProperties(properties, a);
    actorSetPosition(position, a);
    return a;
}

/* What a torpedo of ours carries: its shooter, its team, that its hits go through bots_torpille. */
arm(torpedo)
{
    actorSetParent(me, torpedo);
    actorSetIdleDistance(0.0, torpedo);
    actorSetPropInt("under_water", 1, torpedo);
    actorSetPropInt("enemy", 1, torpedo);
    actorSetPropInt("npc", 1, torpedo);
    actorSetPropInt("actor_id", me, torpedo);
    actorSetPropInt("teamColor", myTeam, torpedo);
    actorSetPropInt("botshot", 1, torpedo);
}

/* A torpedo from the tube, as a player fires one (periscope_move.p func_fbdc): the sub's rotation and
 * velocity, read by the torpedo's script before it moves (surface_torpedo.p func_1488). */
launch(const Float:tube[3], const name[])
{
    new t = spawn(name, tube);
    arm(t);
    new Float:rotation[3];
    actorGetRotation(rotation, 0);
    actorSetRotation(rotation, t);
    actorSetVelocity(vel, t);
    actorUpdateMatrix(t);
    lastTorpedo = t;
}

maskerOn()
{
    if (maskerUses >= floatround(100.0 / maskerCost, 1) || maskerIn)
        return;                                         // the air of a life: 3 maskers, never more
    maskerUses++;
    air = air - maskerCost;
    maskerTime = crewLongMasker ? 450 : 300;            // longMasker (v5200 periscope_move maskerActivate)
    actorSetPropInt("masker", 1, 0);
    actorSetPropInt("masker_on", 1, 0);
}

/* autoMasker (v5200 pscope_player: @HomingLockOn -> periscope_move @autoMasker): a homing torpedo locked on
 * it, its masker comes on by itself; the torpedo loses it (surface_torpedo_p_homing func_4800). It takes it
 * off again soon after when it is not hurt, to fight on. */
homingLocked()
{
    if (!crewAutoMasker || maskerTime || maskerIn || air < maskerCost)
        return;
    maskerOn();
    if (maskerTime)
        autoMaskerAt = frame;
}

forward @HomingLockOn(on, unused);
public @HomingLockOn(on, unused)
{
    #pragma unused unused
    if (lvl && started && on)
        homingLocked();
}

maskerOff()
{
    maskerTime = 0;
    maskerIn = 150;                                     // as a player's button (periscope_move.p, g_752c)
    actorSetPropInt("masker", 0, 0);
    actorSetPropInt("masker_on", 0, 0);
}

/* ---- steering clear ----------------------------------------------------------------------------- */

/* What steerClear (every 3 frames) found, applied every frame by move(). */
new Float:throttleCap = 1.0;         // no faster than this: a wall ahead
new Float:throttleFloor = -1.0;      // no slower: a wall behind
new Float:ceilingY = 100000.0;       // the rock above, if any
new Float:slopeDepth = -100000.0;    // a slope coming up ahead: no lower than this...
new slopeAt = -1000;                 // ...for a second after it was seen

/* Rays ahead: the heading nearest the wanted one with room for the whole hull; the floor below, the rock
 * above. The sub is a capsule 550 long: its nose is NOSE ahead of its middle, and it needs its turning circle
 * (its speed over its turn rate, and the time the turn takes to build up) to get clear of a wall. */
steerClear()
{
    new Float:down[3];
    floatvecset(down, 0.0, -1.0, 0.0);
    floorY = g_1ca0[1] - worldClipLine(g_1ca0, down, 4000.0, COLL_MAP);
    new Float:upward[3];
    floatvecset(upward, 0.0, 1.0, 0.0);
    new Float:above = worldClipLine(g_1ca0, upward, 1500.0, COLL_MAP);
    ceilingY = above < 1500.0 ? g_1ca0[1] + above : 100000.0;

    new Float:speed = floatsqroot(vel[0] * vel[0] + vel[2] * vel[2]);
    new Float:look = NOSE + 450.0 + speed * 80.0;
    new Float:dir[3];
    throttleCap = 1.0;
    throttleFloor = -1.0;
    if (backOutTime) {
        yawSteer = wrapAngle(g_1cc8 + backOutTurn);
        return;
    }
    if (throttleWant < 0.0) {
        headingOf(dir, g_1cc8 + PI);                // backing: what is behind its stern
        if (worldClipLine(g_1ca0, dir, NOSE + 250.0 + speed * 30.0, COLL_MAP) < NOSE + 250.0 + speed * 30.0)
            throttleFloor = 0.3;
        yawSteer = yawWant;
        return;
    }
    // the heading nearest the wanted one with room ahead, on the side it chose to go round (it keeps that
    // side while the way is blocked, or it would hesitate in front of a wall)
    new Float:offsets[] = { 0.0, 0.4, 0.8, 1.3, 1.9, 2.5 };
    new Float:bestRoom = -1.0;
    new Float:bestYaw = yawWant;
    if (!avoidSide) {
        new Float:left = 0.0;
        new Float:right = 0.0;
        headingOf(dir, yawWant + 0.8);
        left = worldClipLine(g_1ca0, dir, look * 2.0, COLL_MAP);
        headingOf(dir, yawWant - 0.8);
        right = worldClipLine(g_1ca0, dir, look * 2.0, COLL_MAP);
        avoidSide = left >= right ? 1 : -1;
    }
    new found = 0;
    for (new pass = 0; pass < 2 && !found; pass++) {
        new Float:way = float(pass == 0 ? avoidSide : -avoidSide);
        for (new i = pass; i < sizeof offsets; i++) {
            new Float:yaw = yawWant + offsets[i] * way;
            headingOf(dir, yaw);
            new Float:room = worldClipLine(g_1ca0, dir, look, COLL_MAP);
            if (room >= look && hullClear(yaw, look)) {
                // also a bit below: a slope coming up
                dir[1] = -0.35;
                floatvecnormalize(dir, dir);
                if (worldClipLine(g_1ca0, dir, look * 0.7, COLL_MAP) < look * 0.7) {
                    slopeDepth = g_1ca0[1] + 200.0;
                    slopeAt = frame;
                }
                bestYaw = yaw;
                bestRoom = room;
                found = 1;
                if (i == 0)
                    avoidSide = 0;                      // the way is clear: no side any more
                break;
            }
            if (room > bestRoom) {
                bestRoom = room;
                bestYaw = yaw;
            }
        }
    }
    yawSteer = wrapAngle(bestYaw);
    // the room in front of its nose, along where it goes now: slow down in time, back off when it is about to
    // touch (it still turns: at a sub's speed the turn rate does not depend on the speed)
    headingOf(dir, g_1cc8);
    new Float:ahead = worldClipLine(g_1ca0, dir, look, COLL_MAP);
    if (ahead < NOSE + 150.0)
        throttleCap = -0.5;
    else if (ahead < look)
        throttleCap = fclamp((ahead - NOSE - 150.0) / (look - NOSE - 150.0), 0.15, 1.0);
    if (bestRoom < NOSE + 150.0)
        throttleCap = fmin(throttleCap, 0.15);
}

/* Room for the hull's width too: two rays along the sides (a ray from the middle misses a corner). */
bool:hullClear(Float:yaw, Float:look)
{
    new Float:dir[3];
    headingOf(dir, yaw);
    new Float:across[3];
    floatvecset(across, dir[2] * BEAM, 0.0, -dir[0] * BEAM);
    new Float:from[3];
    from = g_1ca0;
    floatvecadd(from, across);
    if (worldClipLine(from, dir, look, COLL_MAP) < look)
        return false;
    from = g_1ca0;
    floatvecsub(from, across);
    return worldClipLine(from, dir, look, COLL_MAP) >= look;
}

/* ---- moving: a player's physics ----------------------------------------------------------------- */

move()
{
    // stuck: barely moved for 2 s while trying to
    if (++stuckCheck >= 60) {
        stuckCheck = 0;
        if (!backOutTime && fabs(throttle) > 0.3 && frame - lastBump < 60 && distance(stuckAt, g_1ca0) < 150.0) {
            backOutTime = 50;
            backOutTurn = frandom() > 0.5 ? 1.2 : -1.2;
        }
        stuckAt = g_1ca0;
    }
    if (backOutTime)
        throttleWant = throttle > 0.0 ? -1.0 : 0.8;
    else
        throttleWant = fclamp(throttleWant, throttleFloor, throttleCap);

    // throttle, as a player moves the slider: backwards at half power (periscope_move.p), and braked for a
    // moment after each shot (func_18740: torpedoFireBrakeTime frames at torpedoFireBrakeRate)
    throttle = throttle + fclamp(throttleWant - throttle, -0.05, 0.05);
    throttle = fclamp(throttle, -1.0, 1.0);
    new Float:power = throttle < 0.0 ? throttle / 2.0 : throttle;
    if (brakeTime) {
        brakeTime--;
        brake = brake * brakeRate;
        power = power * brake;
        if (!brakeTime)
            brake = 1.0;
    }

    // turning, as pscope_player.p func_12184: the turn rate goes toward maxTurn * stick * factor, by 2 % a
    // frame while the stick is pushed, 3.8 % when it is let go; factor = sqrt(forward speed) / 10, at least
    // 0.4 (so 0.4 at a sub's speeds)
    new Float:factor = fmax(floatsqroot(fmax(forwardSpeed, 0.0)) / 10.0, 0.4);
    new Float:err = wrapAngle(yawSteer - g_1cc8);
    new Float:rateMax = maxTurn * factor;
    // the stick a pilot would hold: the turn rate wanted is how fast the wanted heading moves, plus a
    // twentieth of the error a frame, within the sub's rate; the stick (-1..1) that gets the rate there
    steerRate = steerRate * 0.8 + wrapAngle(yawSteer - steerBefore) * 0.2;
    steerBefore = yawSteer;
    new Float:want = fclamp(steerRate + err / 20.0, -rateMax, rateMax);
    new Float:stick = fclamp((yawRate + (want - yawRate) / 0.02) / rateMax, -1.0, 1.0);
    if (fabs(stick) < 0.001)
        stick = 0.0;
    yawRate = yawRate + (stick != 0.0 ? 0.02 : 0.038) * (rateMax * stick - yawRate);
    g_1cc8 = wrapAngle(g_1cc8 + yawRate);
    yawRate = 0.999 * yawRate;

    // thrust, then drag along and across the sub (linDrag, latDrag)
    new Float:ahead[3];
    headingOf(ahead, g_1cc8);
    vel[0] = vel[0] + ahead[0] * power * accel;
    vel[2] = vel[2] + ahead[2] * power * accel;
    new Float:flat = floatsqroot(vel[0] * vel[0] + vel[2] * vel[2]);
    if (flat > 0.001) {
        new Float:along = fabs((vel[0] * ahead[0] + vel[2] * ahead[2]) / flat);
        new Float:across = fabs((vel[0] * ahead[2] - vel[2] * ahead[0]) / flat);
        new Float:drag = 1.0 - LIN_DRAG * along - LIN_DRAG * across;
        vel[0] = vel[0] * drag;
        vel[2] = vel[2] * drag;
    }
    forwardSpeed = vel[0] * ahead[0] + vel[2] * ahead[2];
    // ballast toward the wanted depth (-1..1), kept between the floor and the surface: vy -= vy * diveDrag,
    // vy += ballast * diveRate
    if (frame - slopeAt < 30)
        depthWant = fmax(depthWant, slopeDepth);
    new Float:depth = fclamp(depthWant, fmax(floorY + 140.0, -20000.0), fmin(SURFACE - 30.0, ceilingY - 160.0));
    new Float:ballast = fclamp((depth - g_1ca0[1]) * 0.01, -1.0, 1.0);
    if (climbWant != NO_CLIMB && g_1ca0[1] + climbWant * 40.0 < SURFACE - 30.0
        && g_1ca0[1] + climbWant * 40.0 > floorY + 140.0)
        ballast = fclamp(climbWant * diveDrag / diveRate, -1.0, 1.0);  // the vertical speed wanted
    vel[1] = vel[1] - vel[1] * diveDrag + ballast * diveRate;

    // collisions: no going into what it touches, and out of it
    if (bumpTime) {
        new Float:into = floatvecdot(vel, bump);
        if (into < 0.0)
            floatvecaddscale(vel, bump, -into * 1.3);
    }
    new Float:out = floatveclength(push);
    if (out > 5.0)
        floatvecscale(push, 5.0 / out);                 // as a player is pushed: 5 a frame
    floatvecadd(g_1ca0, vel);
    floatvecadd(g_1ca0, push);
    floatveczero(push);
    if (g_1ca0[1] > SURFACE)
        g_1ca0[1] = SURFACE;

    // attitude: roll from the hits (as the game), nose down when diving
    g_1e7c = g_1e7c + g_1c74;
    g_1c74 = 0.8 * g_1c74 - 0.02 * g_1e7c;
    pitchRate = pitchRate + 0.005 * (-0.1 * vel[1] - pitch);     // as a player's sub (func_12184)
    pitch = pitch + pitchRate;
    pitchRate = 0.6 * pitchRate;
    g_1e78 = pitch;
    actorSetRoll(g_1e7c, 0);
    actorSetYaw(g_1cc8, 0);
    actorSetPitch(g_1e78, 0);
    actorSetVelocity(vel, 0);
    new Float:rotation[3];
    actorGetRotation(rotation, 0);
    new Float:torque[3];
    floatvecsubto(torque, rotation, g_3070);
    actorSetTorque(torque, 0);
    g_3064 = vel;
    g_3070 = rotation;
    actorSetPosition(g_1ca0, 0);
    g_11f0 = throttle;
    actorSetPropReal("throttle", throttle, 0);
}

main()
{
}

/* asm
; main: after func_e098 (the sub's properties), is it one of ours, and its look (botLook).
.hook 0xcf80
    .original
    push.c 0
    call @pw_botInit
    push.c 0
    call @botLook
    .return

; func_a848 (movement, every frame): the pilot's, while afloat.
.hook 0xa84c
    push.c 0
    call @pw_botPilot
    jzer @a848_game
    zero.pri
    retn
a848_game:
    .original
    .return

; @torpedoHit(x, y, z, damage, exp, isOpponentNpc, critical, sameTeam, shooter's node, homing, fromNpc):
; hit as a player is (botHitArgs).
.hook 0x866c
    push.adr 0x34                   ; fromNpc
    push.adr 0x30                   ; homing
    push.adr 0x28                   ; same team
    push.adr 0x2c                   ; shooter's node
    push.adr 0x18                   ; damage
    push.c 20
    call @pw_botTorpedoArgs
    .original
    .return

; @explosionHitOnNpc(damage, shooter's node, x, y, z, sameTeam, range, large, fromNpc): the same.
.hook 0x97e4
    push.adr 0x2c                   ; fromNpc
    push.adr 0x24                   ; range
    push.adr 0x20                   ; same team
    push.adr 0x10                   ; shooter's node
    push.adr 0xc                    ; damage
    push.c 20
    call @pw_botExplosionArgs
    .original
    .return

; main, after the sinking: actorSyncRemove(0), func_cb2c (the same) -> after the 215 frames that follow.
.hook 0xdca4
    push.c 0
    call @pw_botKeepsSync
    jnz 0xdcd0
    .original
    .return

.hook 0xdd98
    push.c 0
    call @pw_botKeepsSync
    jzer @sync_done
    push.c 0
    sysreq.n actorSyncRemove, 1
sync_done:
    .original
    .return

; func_edf4 (the game's bot, from func_a848): not for ours, even sinking.
.hook 0xedf8
    push.c 0
    call @pw_botLevel
    jzer @brain_game
    zero.pri
    retn
brain_game:
    .original
    .return

; ---- the bots of the battles against the server's bots: like players --------------------------------

; registerInViews (online bot): its name and level, not the game's "CPU" (name_npc).
.hook 0x2d88
    push.adr -0x180                 ; the label's text, a local of registerInViews
    push.c 4
    call @botLabel
    jnz 0x2da8                      ; done: the label is drawn as the game does
    .original
    .return

; main, online bot: registerInViews(team, camera = 0, label = 1). A bot that looks like a player is in
; the camera's list too, as players are: spectators can follow it.
.hook 0xd530
    push.c 1
    push.c 0
    call @isBot
    push.pri
    push.c 1
    .return

.hook 0xd55c
    push.c 1
    push.c 0
    call @isBot
    push.pri
    push.c 2
    .return

isBot:
    proc
    push.c 0                        ; -4
    push.c 0
    push.adr -4
    push.c "botIndex"
    sysreq.n actorGetPropInt, 3
    load.s.pri -4
    stack 4
    zero.alt
    neq
    retn

; botLook(): the hull of a player's submarine (server.bots.sub<k>: modelship, prop_anim, prop_offset of
; bxml/pscope_plyNN), with three random colours of the customisation (swatch_color), on the body.
; locals: -4 k, -8 sub, -12 other actor, -16 slot, -20 colour, -36 rgb (4 cells), -48 offset (3 cells),
; -0x1b0 text (96 cells), -0x330 model (96 cells), -0x4b0 animation (96 cells)
botLook:
    proc
    stack -0x4b0
    zero.pri
    addr.alt -0x4b0
    fill 0x4b0
    push.c 0
    push.adr -4
    push.c "botIndex"
    sysreq.n actorGetPropInt, 3
    load.s.pri -4
    jzer @look_done
    push.adr -4
    push.c "server.bots.sub%d"
    push.c 0
    push.c 96
    push.adr -0x1b0
    sysreq.n strformat, 5
    push.adr -0x1b0
    sysreq.n sysGetGlobal, 1
    stor.s.pri -8
    load.s.pri -8                   ; 1 to 23
    const.alt 1
    jsgeq @sub_low
    const.s -8, 1
sub_low:
    load.s.pri -8
    const.alt 23
    jsleq @sub_ok
    const.s -8, 23
sub_ok:
    push.adr -8
    push.c "pscope_ply%02d"
    push.c 0
    push.c 96
    push.adr -0x1b0
    sysreq.n strformat, 5
    sysreq.n worldNewActor, 0
    stor.s.pri -12
    push.s -12
    push.adr -0x1b0
    sysreq.n actorReadProperties, 2
    push.s -12
    push.adr -0x330
    push.c "modelship"
    sysreq.n actorGetPropString, 3
    push.s -12
    push.adr -0x4b0
    push.c "prop_anim"
    sysreq.n actorGetPropString, 3
    push.s -12
    push.adr -48
    push.c "prop_offset"
    sysreq.n actorGetPropVector, 3
    push.s -12
    sysreq.n actorKill, 1
    load.s.pri -0x330
    jzer @look_done                 ; no hull: the bot keeps the game's
    push.c 0
    push.c 1
    push.c 1
    push.adr -0x330
    sysreq.n actorSetModel, 4       ; its own copy, for its own colours
    push.c 0
    push.adr -0x4b0
    push.c "prop_anim"
    sysreq.n actorSetPropString, 3
    push.c 0
    push.adr -48
    push.c "prop_offset"
    sysreq.n actorSetPropVector, 3
    sysreq.n worldNewActor, 0       ; the colours of the customisation menu
    stor.s.pri -12
    push.s -12
    push.c "swatch_color"
    sysreq.n actorReadProperties, 2
    zero.s -16
colour_loop:
    push.c 33
    sysreq.n random, 1
    stor.s.pri -20
    push.adr -20
    push.c "color_%02d"
    push.c 0
    push.c 96
    push.adr -0x1b0
    sysreq.n strformat, 5
    push.s -12
    push.adr -36
    push.adr -0x1b0
    sysreq.n actorGetPropRGB, 3
    push.c 0                        ; this actor
    push.c 255
    push.s -28                      ; blue
    push.s -32                      ; green
    push.s -36                      ; red
    push.s -16
    push.c "body_mat"
    sysreq.n actorSetModelColor, 7
    inc.s -16
    load.s.pri -16
    const.alt 3
    jsless @colour_loop
    push.s -12
    sysreq.n actorKill, 1
look_done:
    stack 0x4b0
    zero.pri
    retn

; botLabel(text): "name Lv n" of a bot (botIndex k), 1; 0 for another computer sub.
; locals: -4 k, -8 level, -0x188 work, -0x308 name, -0x488 level text, -0x608 format (96 cells each)
botLabel:
    proc
    stack -0x608
    zero.pri
    addr.alt -0x608
    fill 0x608
    push.c 0
    push.adr -4
    push.c "botIndex"
    sysreq.n actorGetPropInt, 3
    load.s.pri -4
    jzer @label_none
    push.adr -4
    push.c "server.bots.name%d"
    push.c 0
    push.c 96
    push.adr -0x188
    sysreq.n strformat, 5
    push.c 0
    push.c 96
    push.adr -0x308
    push.adr -0x188
    sysreq.n sysGetGlobalArray, 4
    push.adr -4
    push.c "server.bots.lv%d"
    push.c 0
    push.c 96
    push.adr -0x188
    sysreq.n strformat, 5
    push.adr -0x188
    sysreq.n sysGetGlobal, 1
    stor.s.pri -8
    push.c 96
    push.c "lobby_player_lv"        ; "Lv %d", in the language of the game
    push.adr -0x608
    sysreq.n sysGetString, 3
    push.adr -8
    push.adr -0x608
    push.c 0
    push.c 96
    push.adr -0x488
    sysreq.n strformat, 5
    push.adr -0x488
    push.adr -0x308
    push.c "%s %s"
    push.c 0
    push.c 96
    push.s 12
    sysreq.n strformat, 6
    const.pri 1
    jump @label_done
label_none:
    zero.pri
label_done:
    stack 0x608
    retn
*/
