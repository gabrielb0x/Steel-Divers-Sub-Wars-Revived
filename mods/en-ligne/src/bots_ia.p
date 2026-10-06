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
 */

// @target amx/surface_sub.amx
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
// @game g_1f28                online battle
// @game Float:g_3064[3]       velocity of the last frame (network sync)
// @game Float:g_3070[3]       rotation of the last frame (network sync: torque)

#include "sdsw.inc"

/* ---- skill of each level (index: server.bots.level) -------------------------------------------- */
//                          -   normal  difficile  expert
new const SEE_EVERY[] =   { 0,  10,     6,         3 };          // frames between two looks around
new const FIRE_PAUSE[] =  { 0,  40,     12,        0 };          // frames added to the reload
new const Float:MISS_ALLOWED[] = { 0.0, 90.0, 60.0, 45.0 };     // how far off the target a shot may pass
new const Float:DODGE[] = { 0.0, 0.35, 0.8, 1.0 };               // chance to see a torpedo coming
new const HOMING[] =      { 0,  1,      1,         2 };          // homing torpedoes per life

const Float:TORPEDO_ACCEL = 1.2;     // surface_torpedo.p main: func_2ef4(..., 1.2, ...)
const Float:TORPEDO_KEEP = 0.99;     // 1 - friction (0.01, func_1488)
const Float:LIN_DRAG = 0.038;        // linDrag of every pscope_plyNN_stats
const Float:DIVE_DRAG = 0.16;        // diveDrag
const Float:SURFACE = -70.0;         // highest point: under the waterline
const Float:HULL = 70.0;
const Float:NO_CLIMB = 1000.0;             // half the height of a sub, what a torpedo can miss by vertically

new lvl;                             // 0: the game's own bot (offline, or not a computer sub)
new started;
new sunk;
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
new replenishIn;
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
new mates[8];
new mateCount;
new hurtTime;
new lostAt = -10000;                 // when its target vanished under its masker
new Float:lostPos[3];
new Float:lostVel[3];
new blindShots;
new evadeTime;
new Float:evadeYaw;

forward Float:torpedoRange();
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
            // its team loses a sub: every console hears it (bots_partie.pasm @botDown), whatever sank it
            sunk = 1;
            actorSetPropReal("life", 0.0, 0);
            if (sysGetGlobal("server.bots"))
                netCallPublic(UID_GAME_STATE, "@botDown", myTeam, netGetNodeId(), actorGetSyncID(0));
        }
        return 0;
    }
    if (!started)
        start();
    frame++;
    actorSetPropReal("life", g_1c68, 0);               // seen by the others (synced), and by bots_partie
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
    if (!(type & (COLL_MAP | COLL_SUB | COLL_REMOTE)))
        return 0;
    floatvecaddscale(push, normal, 5.0);
    bump = normal;
    bumpTime = 12;
    if (type & COLL_MAP)
        lastBump = frame;
    return 0;
}

/* ---- start -------------------------------------------------------------------------------------- */

start()
{
    started = 1;
    me = actorGetID();
    actorGetPropInt("teamColor", myTeam, 0);
    lifeMax = g_1c68 > 1.0 ? g_1c68 : 150.0;
    lifeBefore = g_1c68;
    readSubmarine();
    torpedoes = torpedoMax;
    homing = HOMING[lvl];
    yawWant = g_1cc8;
    yawSteer = g_1cc8;
    depthWant = fmin(g_1ca0[1], -300.0);
    stuckAt = g_1ca0;
    // the map, the subs (players, bots, the other consoles' copies) and the players' torpedoes
    actorSetCollisionCheck(COLL_MAP | COLL_TORPEDO | COLL_SUB | COLL_REMOTE, 0);
    floatveczero(vel);
    floatveczero(push);
}

/* The characteristics of its submarine: server.bots.sub<k> for the server's bots, else the first one. */
readSubmarine()
{
    new k = 0;
    new sub = 1;
    new name[48];
    actorGetPropInt("botIndex", k, 0);
    if (k) {
        strformat(name, sizeof name, false, "server.bots.sub%d", k);
        sub = sysGetGlobal(name);
        if (sub < 1 || sub > 23)
            sub = 1;
    }
    new a = worldNewActor();
    strformat(name, sizeof name, false, "pscope_ply%02d_stats", sub);
    actorReadProperties(name, a);
    new turnRating = 4;
    new accelRating = 4;
    new diveRating = 4;
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
    actorReadProperties("table_maxturn", a);
    strformat(name, sizeof name, false, "maxTurn_%d", turnRating);
    actorGetPropReal(name, maxTurn, a);
    actorReadProperties("table_below_accel", a);
    strformat(name, sizeof name, false, "belowAccel_%d", accelRating);
    actorGetPropReal(name, accel, a);
    actorReadProperties("table_dive_rate", a);
    strformat(name, sizeof name, false, "diveRate_%d", diveRating);
    actorGetPropReal(name, diveRate, a);
    actorKill(a);
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

timers()
{
    if (reload)
        reload--;
    if (torpedoes < torpedoMax && --replenishIn <= 0) {
        torpedoes++;
        replenishIn = replenishFrames;
    }
    if (bumpTime)
        bumpTime--;
    if (hurtTime)
        hurtTime--;
    if (evadeTime)
        evadeTime--;
    if (backOutTime)
        backOutTime--;
    if (maskerTime && --maskerTime == 0)
        maskerOff();
    if (g_1ca0[1] > -30.0 && air < 100.0)
        air = air + 0.2;                                // as a player: air comes back at the surface only
    if (g_1c68 < lifeBefore - 0.5)
        hurtTime = 120;
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
    new on = 0;
    new masker = 0;
    actorGetPropInt("masker_on", on, actor);
    actorGetPropInt("masker", masker, actor);
    return on || masker;
}

/* The enemies around, and the torpedoes coming. */
lookAround()
{
    new found[16];
    new count = worldFindActors(found, g_1ca0, 40000.0, COLL_SUB | COLL_REMOTE, sizeof found);
    new best = -1;
    new Float:bestScore = 1000000.0;
    new nearest = -1;
    new Float:nearestDistance = 1000000.0;
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
            continue;
        }
        new Float:p[3];
        actorGetPosition(p, a);
        new Float:d = distance(p, g_1ca0);
        new masked = isMasked(a);
        if (!masked && d < nearestDistance) {
            nearest = a;
            nearestDistance = d;
        }
        if (d > 9000.0 || masked)
            continue;                                   // under its masker it cannot be seen, near or far
        new bool:seen = clearLine(g_1ca0, p, 200.0);
        if (!seen && d > 3000.0)
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
    if (target == -1 && nearest != -1 && (!goalValid || frame % 90 < SEE_EVERY[lvl])) {
        actorGetPosition(goal, nearest);            // where the battle is, as the map shows it
        goalValid = 1;
    }
    watchTorpedoes();
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
        if (frandom() > DODGE[lvl])
            continue;
        evadeTime = 45;
        // away from its path, and up or down, away from its depth (a torpedo keeps its depth)
        if (floatveclength(r) > 40.0)
            evadeYaw = yawOf(r);
        else
            evadeYaw = wrapAngle(yawOf(v) + (frandom() > 0.5 ? 1.5708 : -1.5708));
        depthWant = g_1ca0[1] + (g_1ca0[1] > p[1] ? 250.0 : -250.0);
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
    if (target == -1) {
        wander();
        if (evadeTime) {
            yawWant = evadeYaw;
            throttleWant = 1.0;
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
    // an agile target is only hit from close: the shorter the torpedo's run, the less it can turn away
    new Float:wanted = agile() ? 1700.0 : fclamp(range * 0.35, 2200.0, 3000.0);

    if (health < 0.4) {
        // it backs away still firing; under its masker only when the enemy closes in or hits it again
        if (!maskerTime && air >= maskerCost && (d < 1800.0 || (hurtTime && d < 3500.0)))
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
    } else if (d > wanted + 700.0) {
        yawWant = aimYaw;
        throttleWant = 1.0;
    } else if (d < wanted - 1000.0) {
        yawWant = aimYaw;                               // too close: back off, facing it
        throttleWant = -1.0;
    } else {
        yawWant = aimYaw;
        throttleWant = 0.35;
    }
    if (evadeTime) {
        yawWant = evadeYaw;
        throttleWant = 1.0;
    } else {
        // a torpedo leaves along the sub, whose nose goes down as it dives (pitch -> -0.1 * vertical speed,
        // pscope_player.p func_12184): dive or climb at the speed that points it at the target, which also
        // brings it to the target's depth
        depthWant = tPos[1] + tVel[1] * 30.0;
        if (flight && fabs(aim[1]) < 0.5)
            climbWant = fclamp(10.0 * aim[1], -diveRate / diveDrag, diveRate / diveDrag);
    }
    if (d < 900.0 && throttleWant > 0.0)
        throttleWant = -1.0;                            // never ram it
    fire(aim, aimPoint, d, flight);
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
        throttleWant = 1.0;
    }
    if (blindShots >= 2 || !torpedoes || torpedoes < torpedoMax / 2 || reload || frandom() > 0.05)
        return;
    // a shot at a guess: where it would be if it went on, with the same aim as a seen target
    new Float:keepPos[3];
    new Float:keepVel[3];
    keepPos = tPos;
    keepVel = tVel;
    new Float:keepOmega = tOmega;
    tPos = p;
    tVel = lostVel;
    tOmega = 0.0;
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
            if (replenishIn <= 0)
                replenishIn = replenishFrames;
            reload = fireInterval + FIRE_PAUSE[lvl];
            brakeTime = brakeFrames;
            brake = 1.0;
            side = -side;
            blindShots++;
        }
    }
    tPos = keepPos;
    tVel = keepVel;
    tOmega = keepOmega;
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
    if (frame % 240 == 0)
        yawWant = wrapAngle(yawWant + (frandom() - 0.5) * 2.0);
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

/* Where the target will be in n frames, if it keeps its speed and turn rate (a steady turn is a circle). */
new Float:iRadius;                   // of the target's turn, 0: straight (set by intercept)
new Float:iCos;
new Float:iSin;

targetAt(Float:n, Float:p[3])
{
    new Float:t = n + 2.0;                              // the torpedo starts moving a frame or two later
    p = tPos;
    if (iRadius == 0.0) {
        p[0] = p[0] + tVel[0] * t;
        p[2] = p[2] + tVel[2] * t;
    } else {
        new Float:h = tHeading + tOmega * t;
        p[0] = p[0] + iRadius * (iCos - floatcos(h, 0));
        p[2] = p[2] + iRadius * (floatsin(h, 0) - iSin);
    }
    p[1] = p[1] + tVel[1] * fmin(t, 25.0);              // a dive does not last: no further than 25 frames
    if (p[1] > SURFACE)
        p[1] = SURFACE;
}

/* Where to shoot so the torpedo meets the target: the run of the torpedo equals the distance to where the
 * target will be (bisection on the time). aim: unit direction from the tube; returns the frames of the run,
 * 0 if out of range. */
intercept(Float:aim[3], Float:point[3])
{
    new Float:tube[3];
    tubePosition(tube);
    iRadius = 0.0;
    if (lvl >= 2 && fabs(tOmega) >= 0.0002) {
        iRadius = floatsqroot(tVel[0] * tVel[0] + tVel[2] * tVel[2]) / tOmega;
        iCos = floatcos(tHeading, 0);
        iSin = floatsin(tHeading, 0);
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
    if (!torpedoes && !homing)
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
    if (homing && !isMasked(target) && d > 1200.0 && d < 5500.0
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
        if (replenishIn <= 0)
            replenishIn = replenishFrames;
    } else {
        return;
    }
    reload = fireInterval + FIRE_PAUSE[lvl];
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
    air = air - maskerCost;
    maskerTime = 300;
    actorSetPropInt("masker", 1, 0);
    actorSetPropInt("masker_on", 1, 0);
}

maskerOff()
{
    maskerTime = 0;
    actorSetPropInt("masker", 0, 0);
    actorSetPropInt("masker_on", 0, 0);
}

/* ---- steering clear ----------------------------------------------------------------------------- */

/* Rays ahead: the heading nearest the wanted one with nothing in the way; the floor below. */
steerClear()
{
    new Float:down[3];
    floatvecset(down, 0.0, -1.0, 0.0);
    floorY = g_1ca0[1] - worldClipLine(g_1ca0, down, 4000.0, COLL_MAP);

    new Float:speed = floatsqroot(vel[0] * vel[0] + vel[2] * vel[2]);
    new Float:look = 500.0 + speed * 50.0;
    new Float:dir[3];
    if (backOutTime) {
        yawSteer = wrapAngle(g_1cc8 + backOutTurn);
        return;
    }
    if (throttleWant < 0.0) {
        headingOf(dir, g_1cc8 + PI);                // backing: what is behind
        if (worldClipLine(g_1ca0, dir, 450.0, COLL_MAP) < 450.0)
            throttleWant = 0.3;
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
            if (room >= look) {
                // also a bit below: a slope coming up
                dir[1] = -0.35;
                floatvecnormalize(dir, dir);
                if (worldClipLine(g_1ca0, dir, look * 0.7, COLL_MAP) < look * 0.7)
                    depthWant = fmax(depthWant, g_1ca0[1] + 200.0);
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
    headingOf(dir, g_1cc8);
    if (worldClipLine(g_1ca0, dir, 300.0, COLL_MAP) < 300.0 || bestRoom < 250.0)
        throttleWant = fmin(throttleWant, 0.15);    // a wall right ahead: slow down and turn
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
    new Float:depth = fclamp(depthWant, fmax(floorY + 140.0, -20000.0), SURFACE - 30.0);
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
