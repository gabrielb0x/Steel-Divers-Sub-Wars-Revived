; surface_sub: the bots of the battles against the server's bots look like players (their submarine,
; colours, name and level: botIndex k, set by bots_bataille.pasm, server.bots.sub<k> etc.), and every bot
; of the online battles can be harder.
;
; Harder bots in the online battles (server.bots.level, set by the server: 1 normal = the
; game's own bots, 2 difficile, 3 expert). Applies to every computer sub of an online battle, the
; battles against the server's bots and the bots the game adds to fill the teams.
;
; The game's bot (func_edf4, every frame) patrols an area around its spawn point, picks the first enemy
; it finds every 250 frames, and fires straight ahead once it has "aimed" for 250 frames, whatever it
; faces, then waits 300 frames; it moves at 3 units per frame and turns 0.01 radian per frame at most.
; The harder bot: the nearest enemy, aimed at where it will be when the torpedo gets there (its speed
; times the torpedo's flight time), a shot as soon as the bot faces that point and its reload is over,
; and a faster sub that turns faster. The shot itself is still the game's (func_e6a4: line of sight
; checked, the torpedo synced to the other consoles).

;                     -  normal  difficile    expert
.cells $speed         0, 0, float(6.0), float(8.0)          ; units per frame (game: 3)
.cells $turn          0, 0, float(0.025), float(0.035)      ; radians per frame (game: 0.01)
.cells $reload        0, 0, 100, 70                         ; frames between two shots (players: 85)
.cells $retarget      0, 0, 45, 30                          ; frames between two choices of target
.cells $aimcos        0, 0, float(0.985), float(0.994)      ; cosine of the aiming tolerance (10, 6 degrees)
.cells $range         0, 0, float(6000.0), float(7000.0)    ; farthest shot
.var $lvl
.var $turnmax
.var $cooldown
.var $retarget_in
.var $target_was
.var $was 3
.var $target 3
.var $velocity 3
.var $aim 3
.var $dir 3

; main: after func_e098 (the bot's properties), the level of an online bot.
.hook 0xcf80
    .original
    push.c 0
    call @hardInit
    .return

hardInit:
    proc
    push.c 0
    call @botLook
    push.c 0                        ; -4: the "npc" property
    zero $lvl
    load.pri g_1f28                 ; network.online
    jzer @init_done
    push.c 0
    push.adr -4
    push.c "npc"
    sysreq.n actorGetPropInt, 3
    load.s.pri -4
    jzer @init_done
    push.c "server.bots.level"
    sysreq.n sysGetGlobal, 1
    const.alt 2
    jsless @init_done               ; unset or normal: the game's own bot
    const.alt 3
    jsleq @level_ok
    const.pri 3
level_ok:
    stor.pri $lvl
    const.alt $speed
    lidx
    stor.pri g_1c78                 ; speed
    load.pri $lvl
    const.alt $turn
    lidx
    stor.pri $turnmax
init_done:
    stack 4
    zero.pri
    retn

; func_a848 (movement): floatclamp(turn, -0.01, 0.01) -> +-$turnmax for a harder bot.
.hook 0xb650
    load.pri $lvl
    jzer @turn_original
    load.pri $turnmax
    push.pri                        ; max
    const.alt 0x80000000
    xor                             ; -max
    push.pri                        ; min
    .return
turn_original:
    .original
    .return

; func_edf4, every frame: the harder bot's own decisions instead of the game's.
.hook 0xedf8
    load.pri $lvl
    jzer @brain_original
    push.c 0
    call @hardBrain
    zero.pri
    retn
brain_original:
    .original
    .return

; locals: -4 distance, -8 my actor, -12 k, -16 actors found, -56 found[10], -60 my team, -64 its team,
; -68 actor, -72 flight time / dot product
hardBrain:
    proc
    stack -72
    zero.pri
    addr.alt -72
    fill 72
    push.c float(0.01)              ; sinking: nothing to decide
    push g_1c68                     ; life
    sysreq.n floatcmp, 2
    eq.c.pri 1
    jzer @brain_done
    ; a target: the nearest enemy, chosen again every $retarget frames
    dec $retarget_in
    load.pri $retarget_in
    zero.alt
    jsgrtr @check_target
    load.pri $lvl
    const.alt $retarget
    lidx
    stor.pri $retarget_in
    push.c 10
    push.c 0xc0000                  ; the subs (as func_cb7c)
    push.c float(12000.0)
    push.c 0x1ca0                   ; my position
    push.adr -56
    sysreq.n worldFindActorsSorted, 5
    stor.s.pri -16
    push.c 0
    push.adr -60
    push.c "teamColor"
    sysreq.n actorGetPropInt, 3
    sysreq.n actorGetID, 0
    stor.s.pri -8
    const.pri -1
    stor.pri g_1f14
find_loop:
    load.s.pri -12
    load.s.alt -16
    jsgeq @check_target
    load.s.pri -12
    addr.alt -56
    lidx
    stor.s.pri -68
    load.s.alt -8
    eq
    jnz @find_next
    zero.s -64
    push.s -68
    push.adr -64
    push.c "teamColor"
    sysreq.n actorGetPropInt, 3
    load.s.pri -64
    jzer @find_next
    load.s.alt -60
    eq
    jnz @find_next
    load.s.pri -68
    stor.pri g_1f14
    jump @check_target
find_next:
    inc.s -12
    jump @find_loop
check_target:
    load.pri g_1f14
    const.alt -1
    jeq @brain_done
    load.pri g_1f14
    jzer @brain_done
    ; where it is, how fast it goes (same target as last frame)
    push g_1f14
    push.c $target
    sysreq.n actorGetPosition, 2    ; actorGetPosition(position, actor)
    load.pri g_1f14
    load.alt $target_was
    jneq @still
    push.c $was
    push.c $target
    push.c $velocity
    sysreq.n floatvecsubto, 3       ; velocity = position - last position
    jump @moved
still:
    push.c $velocity
    sysreq.n floatveczero, 1
moved:
    push.c float(1.0)
    push.c $target
    push.c $was
    sysreq.n floatveccopyscale, 3
    load.pri g_1f14
    stor.pri $target_was
    ; where it will be when the torpedo gets there
    push.c 0x1ca0
    push.c $target
    push.c $dir
    sysreq.n floatvecsubto, 3
    push.c $dir
    sysreq.n floatveclength, 1
    stor.s.pri -4
    push.c float(30.0)              ; torpedo speed, units per frame (estimate)
    push.s -4
    sysreq.n floatdiv, 2
    stor.s.pri -72
    push.c float(1.0)
    push.c $target
    push.c $aim
    sysreq.n floatveccopyscale, 3
    push.s -72
    push.c $velocity
    push.c $aim
    sysreq.n floatvecaddscale, 3    ; aim = position + velocity * time
    push.c float(1.0)
    push.c $aim
    push.c 0x1cd0
    sysreq.n floatveccopyscale, 3   ; g_1cd0: where func_a848 steers to
    zero g_1e88                     ; steer there every frame
    zero g_1e80                     ; no going back to the spawn area
    zero g_4018
    zero g_1f48
    load.pri $cooldown
    jzer @maybe_fire
    dec $cooldown
    jump @brain_done
maybe_fire:
    load.pri $lvl
    const.alt $range
    lidx
    push.pri
    push.s -4
    sysreq.n floatcmp, 2
    eq.c.pri 1
    jnz @brain_done                 ; too far
    push.c 0x1ca0
    push.c $aim
    push.c $dir
    sysreq.n floatvecsubto, 3
    push.c $dir
    push.c $dir
    sysreq.n floatvecnormalize, 2
    push.c 0x1e60                   ; forward axis (func_a848)
    push.c $dir
    sysreq.n floatvecdot, 2
    stor.s.pri -72
    load.pri $lvl
    const.alt $aimcos
    lidx
    push.pri
    push.s -72
    sysreq.n floatcmp, 2
    eq.c.pri -1
    jnz @brain_done                 ; not facing it yet
    zero g_1e80
    push.c 0
    call 0xe6a4                     ; the game's shot
    zero g_1e80
    load.pri $lvl
    const.alt $reload
    lidx
    stor.pri $cooldown
    zero $retarget_in               ; func_e6a4 forgets the target: choose again
brain_done:
    stack 72
    zero.pri
    retn

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
