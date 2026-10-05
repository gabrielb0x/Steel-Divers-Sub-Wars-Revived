; mode_periscope: the start of a battle against the server's bots (see bots_salon.pasm).

; init: "otherTeamPlayers = 0, so calling @checkGameStartFailure()": not a failure against bots.
.hook 0x13abc
    .original                       ; load.s.pri -0xc: the other team has players
    jnz @others_ok
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
others_ok:
    .return

; inputProperties: an Internet battle lasts 600 seconds (g_1072c); against bots, server.bots.duration.
.hook 0x1911c
    push.c 0
    call @botsTimeLimit
    .original
    .return

; @setNpc: the game creates 4 - players bots in each team that has a player (the first player of the
; team creates them, surface_sub_npc_*: "CPU"). Against the server's bots, the teams are filled to
; server.bots.mine (the team with the most players) and server.bots.other with bots that look like
; players (surface_sub_bot_*, a player's hull and collision, made by mod.toml; botIndex k gives their
; name, submarine and level: bots_ia.pasm), and the host creates those of a team without players.
.hook 0x148f8
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @npc_original
    push.c 0
    call @botsSetNpc
    zero.pri
    retn
npc_original:
    .original
    .return

.cells $npcshift float(-600.0), 0, float(-600.0)
.var $npcextra 3

botsTimeLimit:
    proc
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @limit_done
    push.c "server.bots.duration"
    sysreq.n sysGetGlobal, 1
    jzer @limit_done
    push.pri
    sysreq.n float, 1
    stor.pri g_1072c
limit_done:
    zero.pri
    retn

; locals: -4 players of team 1, -8 of team 2, -12 the players' team, -16 team, -20 bots of the team,
; -24 j, -28 first slot of the team, -32 actor, -36 slot, -40 players of the team, -44 position,
; -48 pass (0: the players' team, 1: the other), -52 k (bot number, 1 to 7)
botsSetNpc:
    proc
    stack -52
    zero.pri
    addr.alt -52
    fill 52
    push.c 1
    sysreq.n gfxSelectRenderer, 1
    push.c "player.stage"
    sysreq.n sysGetGlobal, 1
    push.pri
    push.c 4
    call 0x10120                    ; the six bot positions of the map (g_f808)
    push.c 1
    push.c 4
    call 0x4890                     ; getTeamPlayerCount(1)
    stor.s.pri -4
    push.c 2
    push.c 4
    call 0x4890
    stor.s.pri -8
    const.s -12, 1
    load.s.pri -8
    load.s.alt -4
    jsleq @teams                    ; more players in team 2: it is the players' team
    const.s -12, 2
teams:
    push.c 0
    push.c "bots.alive1"            ; bots afloat, for the end of the battle (bots_partie.pasm)
    sysreq.n sysSetGlobal, 2
    push.c 0
    push.c "bots.alive2"
    sysreq.n sysSetGlobal, 2
pass_loop:
    load.s.pri -48                  ; team: the players' team first, then the other
    jnz @pass_other
    load.s.pri -12
    jump @pass_team
pass_other:
    load.s.pri -12
    const.alt 3
    sub.alt                         ; 3 - the players' team
pass_team:
    stor.s.pri -16
    load.s.pri -48
    jnz @target_other
    push.c "server.bots.mine"
    jump @target_get
target_other:
    push.c "server.bots.other"
target_get:
    sysreq.n sysGetGlobal, 1
    stor.s.pri -20
    load.s.pri -16
    eq.c.pri 1
    jzer @players_red
    load.s.alt -4
    jump @players_got
players_red:
    load.s.alt -8
players_got:
    stor.s.alt -40
    load.s.pri -20
    sub                             ; bots = size - players, 0 to 4
    stor.s.pri -20
    zero.alt
    jsgeq @bots_positive
    zero.s -20
bots_positive:
    load.s.pri -20
    const.alt 4
    jsleq @bots_counted
    const.s -20, 4
bots_counted:
    load.s.pri -16
    eq.c.pri 1
    jzer @alive_red
    load.s.pri -20
    stor.pri g_10adc                ; gBlueTeamNum, as the game does
    push.s -20
    push.c "bots.alive1"
    jump @alive_set
alive_red:
    load.s.pri -20
    stor.pri g_10ae0                ; gRedTeamNum
    push.s -20
    push.c "bots.alive2"
alive_set:
    sysreq.n sysSetGlobal, 2
    ; who creates them: the team's first player, or the host for a team without players
    load.s.pri -40
    jzer @by_host
    push.s -16
    push.c 4
    call 0x5300                     ; node of the team's first player
    push.pri
    sysreq.n netGetNodeId, 0
    pop.alt
    eq
    jzer @skip_team
    jump @create
by_host:
    sysreq.n netIsMaster, 0
    jzer @skip_team
create:
    zero.s -28                      ; slots 0-2: blue, 3-5: red (npcNum <= 2 is the blue team)
    load.s.pri -16
    eq.c.pri 1
    jnz @first_slot
    const.s -28, 3
first_slot:
    zero.s -24
create_loop:
    load.s.pri -24
    load.s.alt -20
    jsgeq @next_pass
    inc.s -52                       ; bot number k
    load.s.pri -24                  ; slot = first + min(j, 2)
    const.alt 2
    jsleq @slot_j
    const.pri 2
slot_j:
    load.s.alt -28
    add
    stor.s.pri -36
    const.alt 4                     ; position: row slot of g_f808 (Pawn 2D array)
    smul
    const.alt 0xf808
    add
    move.alt
    load.i
    add
    stor.s.pri -44
    load.s.pri -24                  ; a fourth bot: next to the third
    eq.c.pri 3
    jzer @position_ok
    push.c $npcshift
    push.s -44
    push.c $npcextra
    sysreq.n floatvecsubto, 3
    const.pri $npcextra
    stor.s.pri -44
position_ok:
    push.s -44
    load.s.pri -16
    eq.c.pri 1
    jzer @name_red
    push.c "surface_sub_bot_blue"
    jump @name_ok
name_red:
    push.c "surface_sub_bot_red"
name_ok:
    push.c 8
    call 0x2ea0                     ; spawnActor(name, position)
    stor.s.pri -32
    push.s -32
    push.s -36
    push.c "npcNum"
    sysreq.n actorSetPropInt, 3
    push.s -32
    push.s -52
    push.c "botIndex"
    sysreq.n actorSetPropInt, 3
    load.s.pri -24                  ; the first three in g_f868 (blue) or g_f874 (red), as the game does
    const.alt 2
    jsgrtr @created
    load.s.pri -16
    eq.c.pri 1
    jzer @keep_red
    const.alt 0xf868
    jump @keep
keep_red:
    const.alt 0xf874
keep:
    load.s.pri -24
    shl.c.pri 2
    add
    move.alt
    load.s.pri -32
    stor.i
created:
    inc.s -24
    jump @create_loop
skip_team:                          ; not ours to create: the numbers still go on
    load.s.pri -52
    load.s.alt -20
    add
    stor.s.pri -52
next_pass:
    inc.s -48
    load.s.pri -48
    const.alt 1
    jsleq @pass_loop
    const.s -16, 1                  ; the team counters of the HUD, bots included (bots_hud.pasm)
hud_loop:
    push.s -16
    push.c 4
    call 0x4890                     ; getTeamPlayerCount(team)
    stor.s.pri -20
    push.adr -20
    push.adr -16
    push.c "@setTeamCount"
    push.c 10010                    ; UID_HUD
    sysreq.n sysCallPublic, 4
    inc.s -16
    load.s.pri -16
    const.alt 2
    jsleq @hud_loop
    stack 52
    zero.pri
    retn
