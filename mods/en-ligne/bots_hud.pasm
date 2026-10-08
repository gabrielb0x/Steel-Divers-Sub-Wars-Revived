; hud: the team counters (top right) count the bots afloat with the players, against the server's bots
; (bots.alive1, bots.alive2: bots_bataille.pasm, bots_partie.pasm).

.heapstack 0x4000                   ; 16 KB of heap and stack, as the game's scripts (v5200's: 8 KB)

; @setTeamCount(team, count): count += bots afloat of the team.
.hook 0x3d50
    push.c "server.bots"
    sysreq.n sysGetGlobal, 1
    jzer @count_original
    load.s.pri 12
    eq.c.pri 1
    jzer @count_red
    push.c "bots.alive1"
    jump @count_get
count_red:
    push.c "bots.alive2"
count_get:
    sysreq.n sysGetGlobal, 1
    load.s.alt 16
    add
    stor.s.pri 16
count_original:
    .original
    .return
