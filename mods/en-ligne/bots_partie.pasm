; game_state: the end of a battle against the server's bots (see bots_salon.pasm).
;
; The game ends a battle when fewer than two teams have players afloat (checkGameOverTeamBattle, on the
; host); its bots do not count. Against the server's bots, a team's bots afloat count with its players
; (bots.alive1, bots.alive2: set by bots_bataille.pasm, lowered by @botDown when a bot sinks), and a bot
; that sinks is checked for the end of the battle like a player who sinks.

; checkGameOverTeamBattle: getTeamPlayerCount(team) (func_3fec) -> teamRemaining(team), at both calls.
.hook 0x6854
    call @teamRemaining
    .return

.hook 0x68bc
    call @teamRemaining
    .return

teamRemaining:
    proc
    push.s 12
    push.c 4
    call 0x3fec                     ; getTeamPlayerCount(team)
    push.pri
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @players_only
    load.s.pri 12
    eq.c.pri 1
    jzer @remaining_red
    push.c "bots.alive1"
    jump @remaining_get
remaining_red:
    push.c "bots.alive2"
remaining_get:
    sysreq.n sysGetGlobal, 1
    pop.alt
    add
    retn
players_only:
    pop.pri
    retn

; @eventMessageAISubDead(node, syncId): the game's message when a computer sub sinks from a torpedo. Not
; sent when one sinks from an explosion (@explosionHitOnNpc), and its sub is found again by its sync id, which
; can fail: the bots' pilot (bots_ia.p) says it itself, once, with its team, by @botDown below. Here, only a
; check of the end of the battle.
.hook 0x7160
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @aisub_original
    push.c 0
    call @scheduleCheck
aisub_original:
    .original
    .return

; @botDown(team): a bot of this team sank (netCallPublic of bots_ia.p, heard by every console).
.public @botDown
botDown:
    proc
    load.s.pri 12
    eq.c.pri 1
    jzer @down_red
    const.pri "bots.alive1"
    jump @down_count
down_red:
    const.pri "bots.alive2"
down_count:
    push.pri
    push.pri
    sysreq.n sysGetGlobal, 1
    add.c -1
    zero.alt
    jsgeq @down_store
    zero.pri
down_store:
    pop.alt
    push.pri
    push.alt
    sysreq.n sysSetGlobal, 2
    stack -4                        ; -4: the HUD's team counter, bots included (bots_hud.pasm)
    push.s 12
    push.c 4
    call 0x3fec                     ; getTeamPlayerCount(team)
    stor.s.pri -4
    push.adr -4
    push.adr 12
    push.c "@setTeamCount"
    push.c 10010                    ; UID_HUD
    sysreq.n sysCallPublic, 4
    stack 4
    push.c 0
    call @scheduleCheck
    zero.pri
    retn

; scheduleCheck(): one second from now, checkGameOverMulti (func_6e70).
; locals: -8 session time (2 cells)
scheduleCheck:
    proc
    stack -8
    zero.pri
    addr.alt -8
    fill 8
    push.c 2
    push.adr -8
    sysreq.n netGetSessionTime, 2
    push.c 0
    push.c 0
    push.s -4
    push.c 0
    push.c 16
    call 0x6f44                     ; @scheduleCheckGameOver(0, time, 0, 0)
    stack 8
    zero.pri
    retn
