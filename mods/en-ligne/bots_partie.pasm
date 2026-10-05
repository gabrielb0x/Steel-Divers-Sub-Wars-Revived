; game_state: the end of a battle against the server's bots (see bots_salon.pasm).
;
; The game ends a battle when fewer than two teams have players afloat (checkGameOverTeamBattle, on the
; host); its bots do not count. Against the server's bots, a team's bots afloat count with its players
; (bots.alive1, bots.alive2: set by bots_bataille.pasm, lowered here when a bot sinks), and a bot that
; sinks is checked for the end of the battle like a player who sinks.

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

; @eventMessageAISubDead(node, syncId): every console hears that a bot sank (netCallPublic).
.hook 0x7160
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @aisub_original
    push.s 16
    push.s 12
    push.c 8
    call @botSunk
aisub_original:
    .original
    .return

; locals: -4 actor, -8 its team, -12 name of the count, -20 session time (2 cells)
botSunk:
    proc
    stack -20
    zero.pri
    addr.alt -20
    fill 20
    push.s 16
    push.s 12
    sysreq.n actorGetFromSyncID, 2
    stor.s.pri -4
    eq.c.pri -1
    jnz @sunk_done
    push.s -4
    push.adr -8
    push.c "teamColor"
    sysreq.n actorGetPropInt, 3
    load.s.pri -8
    eq.c.pri 1
    jzer @sunk_red
    const.pri "bots.alive1"
    jump @sunk_count
sunk_red:
    const.pri "bots.alive2"
sunk_count:
    stor.s.pri -12
    push.s -12
    sysreq.n sysGetGlobal, 1
    add.c -1
    zero.alt
    jsgeq @sunk_store
    zero.pri
sunk_store:
    push.pri
    push.s -12
    sysreq.n sysSetGlobal, 2
    push.s -8                       ; the HUD's team counter, bots included (bots_hud.pasm)
    push.c 4
    call 0x3fec                     ; getTeamPlayerCount(team)
    stor.s.pri -4
    push.adr -4
    push.adr -8
    push.c "@setTeamCount"
    push.c 10010                    ; UID_HUD
    sysreq.n sysCallPublic, 4
    push.c 2                        ; one second from now, checkGameOverMulti (func_6e70)
    push.adr -20
    sysreq.n netGetSessionTime, 2
    push.c 0
    push.c 0
    push.s -16
    push.c 0
    push.c 16
    call 0x6f44                     ; @scheduleCheckGameOver(0, time, 0, 0)
sunk_done:
    stack 20
    zero.pri
    retn
