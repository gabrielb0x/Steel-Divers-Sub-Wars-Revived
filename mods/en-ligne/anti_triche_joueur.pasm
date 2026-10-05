; pscope_player: damage cancelled without a reason of the game (invincibility: the developers' flag
; player.muteki, or a script patched to skip the damage). See anti_triche_tir.pasm.

.var $damage                        ; the damage as it came, before the game's checks

; @eventDamageTorp(damage, ...): its first argument.
.hook 0xd770
    load.s.pri 12
    stor.pri $damage
    .original
    .return

; after "if (player.finished || mode.gameover || player.muteki || player.demo || debug.move) damage = 0":
; a damage gone, with none of the game's own reasons (player.muteki is never one online).
.hook 0xd844
    load.s.pri 12
    jnz @damage_done                ; still there
    load.pri $damage
    zero.alt
    jsleq @damage_done              ; nothing came (a positive float is a positive cell)
    push.c 0
    call @noDamageReason
    jnz @damage_done
    push.c 1                        ; caught: damage cancelled
    push.c 4
    call @acKick
damage_done:
    .original
    .return

noDamageReason:
    proc
    push.c "player.finished"
    sysreq.n sysGetGlobal, 1
    jnz @reason_found
    push.c "mode.gameover"
    sysreq.n sysGetGlobal, 1
    jnz @reason_found
    push.c "player.demo"
    sysreq.n sysGetGlobal, 1
    jnz @reason_found
    push.c "debug.move"
    sysreq.n sysGetGlobal, 1
    jnz @reason_found
    push.c "network.internet"
    sysreq.n sysGetGlobal, 1
    not                             ; missions, local wireless: not our business
reason_found:
    retn

acKick:                             ; acKick(seen): periscope_move's @sdswKick (anti_triche_tir.pasm)
    proc
    push.adr 12
    push.c "@sdswKick"
    push.c 10001                    ; UID_PERISCOPE_MOVE
    sysreq.n sysCallPublic, 3
    zero.pri
    retn
