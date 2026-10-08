; periscope_move: torpedoes that do not run out, shots too close together, a speed no submarine has; and the
; exit of a game caught cheating (here or in pscope_player, anti_triche_joueur.pasm), during an Internet battle
; the server watches (server.anticheat, set by the server at each search for a match).
; Times: netGetSessionTimeLo(), milliseconds of the session.
;
; The game's limits (bxml/pscope_plyNN_stats, table_above_accel): a sub waits torpedoFireInterval (70 to 110
; frames) + 15 frames between two shots, so never under a second; its top speed is accel / linDrag, 0.54 /
; 0.038 = 14.2 units per frame (430 per second) for the fastest. Margins: three shots within a second of the
; one before, or 20 units per frame (600 per second) three seconds in a row.

.heapstack 0x4000                   ; 16 KB of heap and stack, as the game's scripts (v5200's: 8 KB)

.var $torpedoes                     ; torpedoes before the shot
.var $lastShot
.var $quick                         ; shots within a second of the previous one
.var $window                        ; start of the current second
.var $windowPos 3                   ; position then
.var $fastSeconds
.var $pos 3
.var $step 3
.var $kick                          ; what was caught: the exit waits for the main loop

; fireTorpedo, right after a torpedo left: "g_4ff0++".
.hook 0x10aa8
    push.c 0
    call @acShot
    .original
    .return

; after "if (!player.muteki) { torpedoes--; ... }": it must have gone down.
.hook 0x10b18
    push.c 0
    call @acCounted
    .original
    .return

; main loop, every frame: the speed, and the exit once caught.
.hook 0x1ab34
    push.c 0
    call @acFrame
    push.c 0
    call @acExit
    .original
    .return

; @sdswKick(seen): seen = what was caught (bits, see server/realm.py). The save keeps the last kick: what
; was caught (save.sdsw.cheat) and its number (save.sdsw.kick), told to the server at each search for a
; match (acReport in mod.toml), which deals with each kick once. The battle is left at the next frame: the
; damage check runs inside the network's messages, where the network must not be shut down.
.public @sdswKick
sdswKick:
    proc
    push.c 0
    call @acWatching
    jzer @kick_done
    load.pri $kick
    jnz @kick_same                  ; caught again before leaving: the same kick
    push.c "save.sdsw.kick"
    sysreq.n sysGetGlobal, 1
    add.c 1
    const.alt 0x7fff
    and
    push.pri
    push.c "save.sdsw.kick"
    sysreq.n sysSetGlobal, 2
    push.c 0
    push.c "save.sdsw.cheat"
    sysreq.n sysSetGlobal, 2
kick_same:
    push.c "save.sdsw.cheat"
    sysreq.n sysGetGlobal, 1
    load.s.alt 12
    or
    push.pri
    push.c "save.sdsw.cheat"
    sysreq.n sysSetGlobal, 2
    push.c 1                        ; the Internet menu saves it
    push.c "mode.savedata.multi"
    sysreq.n sysSetGlobal, 2
    load.pri $kick
    load.s.alt 12
    or
    stor.pri $kick
kick_done:
    zero.pri
    retn

; acExit(): what @handleClicked does when the player leaves a battle after sinking ("exit" button).
; locals: -4 the argument of @doGameOver
acExit:
    proc
    push.c 0
    load.pri $kick
    jzer @exit_done
    zero $kick
    push.c "mode.gameover"           ; ended meanwhile: the save keeps it all the same
    sysreq.n sysGetGlobal, 1
    jnz @exit_done
    push.c 1
    push.c "forbid.startButton"
    sysreq.n sysSetGlobal, 2
    push.c 1
    push.c "player.exit"
    sysreq.n sysSetGlobal, 2
    push.c -1
    push.c "mode.teamwon"
    sysreq.n sysSetGlobal, 2
    push.c 1
    push.c "mode.manualExit"
    sysreq.n sysSetGlobal, 2
    push.c 0
    push.c 0
    push.c 0x100006c
    sysreq.n sndSE, 3
    push.c "mode_internet_menu"
    push.c 4
    call 0x05a4                     ; sysSetMode
    push.c 0
    call 0xec0c                     ; gfxBlackout()
    push.adr -4
    push.c "@doGameOver"
    push.c 10000                    ; UID_MODE
    sysreq.n sysCallPublic, 3
    sysreq.n netIsInitialized, 0
    jzer @exit_done
    sysreq.n netFinalize, 0         ; mode_internet_menu only does it when coming back from the lobby
exit_done:
    stack 4
    zero.pri
    retn

acWatching:                         ; 1 during an Internet battle the server watches
    proc
    push.c "server.anticheat"
    sysreq.n sysGetGlobal, 1
    jzer @watch_done
    load.pri g_3d48                 ; network.online
    jzer @watch_done
    load.pri g_3d4c                 ; network.internet (not a local wireless battle)
    jzer @watch_done
    push.c "mode.ready"
    sysreq.n sysGetGlobal, 1
    jzer @watch_done
    push.c "mode.gameover"
    sysreq.n sysGetGlobal, 1
    not
watch_done:
    retn

acShot:
    proc
    push.c 0                        ; -4: now
    load.pri g_4fec
    stor.pri $torpedoes
    push.c 0
    call @acWatching
    jzer @shot_done
    sysreq.n netGetSessionTimeLo, 0
    stor.s.pri -4
    load.alt $lastShot
    sub                             ; now - last
    const.alt 1000
    jsgeq @shot_slow
    load.pri $lastShot
    jzer @shot_slow                 ; the first shot
    inc $quick
    load.pri $quick
    const.alt 3
    jsless @shot_keep
    push.c 4                        ; caught: shots too close together
    push.c 4
    call @acKick
    jump @shot_keep
shot_slow:
    zero $quick
shot_keep:
    load.s.pri -4
    stor.pri $lastShot
shot_done:
    stack 4
    zero.pri
    retn

acCounted:
    proc
    push.c 0
    call @acWatching
    jzer @counted_done
    load.pri g_4fec
    load.alt $torpedoes
    jneq @counted_done              ; one less: fine
    push.c 2                        ; caught: the torpedoes do not run out
    push.c 4
    call @acKick
counted_done:
    zero.pri
    retn

; locals: -4 now, -8 player, -12 distance, -16 elapsed
acFrame:
    proc
    stack -16
    zero.pri
    addr.alt -16
    fill 16
    push.c 0
    call @acWatching
    jnz @frame_watch
    zero $window                    ; start again next battle
    zero $fastSeconds
    zero $lastShot
    zero $quick
    jump @frame_done
frame_watch:
    push.c 10100                    ; UID_PLAYER: the player's sub
    sysreq.n worldFindActorUID, 1
    stor.s.pri -8
    jzer @frame_done
    sysreq.n netGetSessionTimeLo, 0
    stor.s.pri -4
    push.s -8
    push.c $pos
    sysreq.n actorGetPosition, 2
    load.pri $window
    jnz @frame_window
    load.s.pri -4                   ; first frame: a window starts
    stor.pri $window
    push.c float(1.0)
    push.c $pos
    push.c $windowPos
    sysreq.n floatveccopyscale, 3
    jump @frame_done
frame_window:
    load.s.pri -4
    load.alt $window
    sub
    stor.s.pri -16                  ; elapsed (ms)
    const.alt 1000
    jsless @frame_done
    push.c $windowPos               ; horizontal distance since the start of the window
    push.c $pos
    push.c $step
    sysreq.n floatvecsubto, 3
    const.pri $step
    add.c 4
    move.alt
    zero.pri
    stor.i                          ; step.y = 0
    push.c $step
    sysreq.n floatveclength, 1
    stor.s.pri -12
    push.s -16                      ; limit: 0.6 units per millisecond
    sysreq.n float, 1
    push.c float(0.6)
    push.pri
    sysreq.n floatmul, 2
    push.pri
    push.s -12
    sysreq.n floatcmp, 2            ; distance vs limit
    eq.c.pri 1
    jzer @frame_slow
    inc $fastSeconds
    load.pri $fastSeconds
    const.alt 3
    jsless @frame_next
    push.c 8                        ; caught: impossible speed
    push.c 4
    call @acKick
    jump @frame_next
frame_slow:
    zero $fastSeconds
frame_next:
    load.s.pri -4
    stor.pri $window
    push.c float(1.0)
    push.c $pos
    push.c $windowPos
    sysreq.n floatveccopyscale, 3
frame_done:
    stack 16
    zero.pri
    retn

acKick:                             ; acKick(seen)
    proc
    push.s 12
    push.c 4
    call @sdswKick
    zero.pri
    retn
