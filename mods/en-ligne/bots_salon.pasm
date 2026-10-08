; mode_lobby: the battles against the server's bots (tools/amxasm.py syntax).
;
; The server sets the script globals server.bots.* in the game (notifications 999001/999002, see the patch
; of MyNotificationEventHandler in mod.toml) when a player has been alone in a match for bots_delay seconds:
;   server.bots            1: this match is played against bots
;   server.bots.mine       size of the players' team (bots fill it)
;   server.bots.other      size of the other team (all bots)
;   server.bots.stage      the map (player.stage, 10 to 19), 0: random
;   server.bots.countdown  countdown before the battle, in milliseconds
;   server.bots.duration   length of the battle, in seconds
;   server.bots.name<k>, sub<k>, lv<k>   bot k (1 to 7): its name, submarine and level, as a player has
; Bot k: the bots of the players' team first (the team with the most players, team 1 on a tie), then
; those of the other team; bots_bataille.pasm numbers them the same way.
;
; The bots join the lobby one by one, shown in the team lists like players (name, submarine, level,
; ready); once they are all in, the host starts the countdown. The game itself only counts down when
; each team has a player (checkCountdownStart, func_eb14).

.heapstack 0x4000                   ; 16 KB of heap and stack, as the game's scripts (v5200's: 8 KB)

.var $shown                         ; bots shown in the lobby so far
.var $total                         ; bots of the match
.var $wait                          ; frames before the next one joins

; func_b518 "each team has a player": against bots, true once they have all joined.
.hook 0xb51c
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @teams_original
    push.c 0
    call @botsTotal
    load.alt $shown
    sleq                            ; total <= shown
    retn
teams_original:
    .original
    .return

; func_eb14: the countdown lasts server.bots.countdown milliseconds instead of 120 seconds
; (PRI holds the time elapsed, ALT receives the length, then sub.alt).
.hook 0xebf8
    push.pri
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @countdown_original
    push.c "server.bots.countdown"
    sysreq.n sysGetGlobal, 1
    move.alt
    pop.pri
    .return
countdown_original:
    pop.pri
    .original
    .return

; main loop, every frame: the bots join, then the host starts the countdown.
.hook 0x1623c
    push.c 0
    call @botsTick
    .original
    .return

; @updateTeams, after the empty rows: the bots that have joined, in the rows after the players.
.hook 0x132a0
    push.c 0
    call @botsRows
    .original
    .return

; checkStartGame: the map the server chose, rather than a random one.
.hook 0x1388c
    .original                       ; getRandomStage()
    push.pri
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @map_random
    push.c "server.bots.stage"
    sysreq.n sysGetGlobal, 1
    jzer @map_random
    stack 4                         ; the random stage is dropped, PRI holds the server's
    .return
map_random:
    pop.pri
    .return

botsTick:
    proc
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jnz @tick_bots
    zero $shown                     ; not (or no longer) a battle against bots
    zero $wait
    zero.pri
    retn
tick_bots:
    push.c 0
    call @botsTotal
    stor.pri $total
    load.alt $shown
    jsleq @tick_all_in              ; total <= shown: everyone is in
    load.pri $wait
    jzer @tick_join
    dec $wait
    zero.pri
    retn
tick_join:
    const.pri 20                    ; the next one in two thirds of a second
    stor.pri $wait
    inc $shown
    push.c 0
    push.c 4
    call 0x12f8c                    ; @updateTeams(0): the lists, with the new bot
    push.c 0
    push.c 0
    push.c 0x10000ce                ; the sound of a player joining (@connectOn)
    sysreq.n sndSE, 3
    zero.pri
    retn
tick_all_in:
    load.pri g_5030                 ; gCountingDown
    jnz @tick_done
    sysreq.n netIsMaster, 0
    jzer @tick_done
    push.c 0
    push.c 4
    call 0xb5b4                     ; checkCountdownStart(0)
tick_done:
    zero.pri
    retn

; botsTotal(): bots of both teams
botsTotal:
    proc
    push.c 0
    push.c 4
    call @botsInTeam
    push.pri
    push.c 1
    push.c 4
    call @botsInTeam
    pop.alt
    add
    retn

; botsInTeam(t): bots of team index t (0 blue, 1 red): its size minus the players in its list, 0 to 4.
; locals: -8 players of team 0, -4 of team 1, -12 size of the team
botsInTeam:
    proc
    stack -12
    zero.pri
    addr.alt -12
    fill 12
    push.c 0
    push.c 2
    push.adr -8
    push.c "network.teamNodes.teamcounts"
    sysreq.n sysGetGlobalArray, 4
    load.s.pri -4
    load.s.alt -8
    sgrtr                           ; the players' team: 1 if team 1 has more players
    load.s.alt 12
    eq
    jzer @in_other
    push.c "server.bots.mine"
    jump @in_size
in_other:
    push.c "server.bots.other"
in_size:
    sysreq.n sysGetGlobal, 1
    stor.s.pri -12
    load.s.pri 12
    jzer @in_team0
    load.s.alt -4
    jump @in_players
in_team0:
    load.s.alt -8
in_players:
    load.s.pri -12
    sub
    zero.alt
    jsgeq @in_positive
    zero.pri
in_positive:
    const.alt 4
    jsleq @in_done
    const.pri 4
in_done:
    stack 12
    retn

; botsRows(): bot k in the list of its team, after the players, if it has joined (k <= $shown).
; locals: -4 team index, -8 j, -12 bots of the team, -16 k, -20 row, -24 bots of the players' team,
; -28 the players' team, -36 players in the lists (2 cells), -40 value, -44 animation,
; -0x1ac text (96 cells), -0x32c name (96 cells)
botsRows:
    proc
    stack -0x32c
    zero.pri
    addr.alt -0x32c
    fill 0x32c
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @rows_done
    push.c 0
    push.c 2
    push.adr -36
    push.c "network.teamNodes.teamcounts"
    sysreq.n sysGetGlobalArray, 4
    load.s.pri -32
    load.s.alt -36
    sgrtr
    stor.s.pri -28
    push.s -28
    push.c 4
    call @botsInTeam
    stor.s.pri -24
    zero.s -4
rows_team:
    push.s -4
    push.c 4
    call @botsInTeam
    stor.s.pri -12
    zero.s -16                      ; first k of the team: 1, or after the players' team
    load.s.pri -4
    load.s.alt -28
    jeq @rows_first
    load.s.pri -24
    stor.s.pri -16
rows_first:
    zero.s -8
rows_bot:
    load.s.pri -8
    load.s.alt -12
    jsgeq @rows_next_team
    inc.s -16
    load.s.pri -16
    load.alt $shown
    jsgrtr @rows_next_team          ; not joined yet (nor the next ones)
    load.s.pri -4                   ; row: after the players of the team
    jzer @rows_t0
    load.s.alt -32
    jump @rows_row
rows_t0:
    load.s.alt -36
rows_row:
    load.s.pri -8
    add
    stor.s.pri -20
    push.adr -16                    ; the name of bot k
    push.c "server.bots.name%d"
    push.c 0
    push.c 96
    push.adr -0x1ac
    sysreq.n strformat, 5
    push.c 0
    push.c 96
    push.adr -0x32c
    push.adr -0x1ac
    sysreq.n sysGetGlobalArray, 4
    push.adr -20                    ; in the row's text box
    push.adr -4
    push.c "Text_g%02d_n%02d"
    push.c 0
    push.c 96
    push.adr -0x1ac
    sysreq.n strformat, 6
    push.adr -0x32c
    push.adr -0x1ac
    push g_e7d0
    sysreq.n actorReplaceStringf, 3
    push.adr -20                    ; ready, like a player who pressed OK
    push.adr -4
    push.c "status_g%02d_n%02d"
    push.c 0
    push.c 96
    push.adr -0x1ac
    sysreq.n strformat, 6
    push.adr -44
    push g_e7d0
    push.c "icon_status"
    push.adr -0x1ac
    push.c 16
    call 0x0e1c                     ; playLayoutPaneAnim
    stor.s.pri -44
    push.c 0
    push.s -44
    sysreq.n actorSetAnimSpeed, 2
    push.c float(1.0)
    push.s -44
    sysreq.n actorSetAnimFrame, 2
    push.adr -16                    ; its submarine
    push.c "server.bots.sub%d"
    push.c 0
    push.c 96
    push.adr -0x1ac
    sysreq.n strformat, 5
    push.adr -0x1ac
    sysreq.n sysGetGlobal, 1
    push.pri
    push.s -20
    push.s -4
    push.c 12
    call 0x11e00                    ; the submarine's icon
    push.adr -16                    ; its level
    push.c "server.bots.lv%d"
    push.c 0
    push.c 96
    push.adr -0x1ac
    sysreq.n strformat, 5
    push.adr -0x1ac
    sysreq.n sysGetGlobal, 1
    push.c 1
    push.pri
    push.s -20
    push.s -4
    push.c 16
    call 0x11f68                    ; "Lv n"
    inc.s -8
    jump @rows_bot
rows_next_team:
    inc.s -4
    load.s.pri -4
    const.alt 1
    jsleq @rows_team
rows_done:
    stack 0x32c
    zero.pri
    retn
