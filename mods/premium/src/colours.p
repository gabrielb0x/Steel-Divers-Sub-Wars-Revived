/* mode_title: the colours of the patterns ("motifs") the premium mod unlocked (option debloquer).
 *
 * When a reward unlocks a pattern, the game gives it its default colours: the three swatches of
 * bxml/sub_color_set ("pattern_NN", NN = pattern - 1) go into save.sub.patternN.color0..2 (unlockPattern of
 * mode_periscope, mode_peri_result, and v5200's mode_title). The mod unlocks the patterns in
 * sysDLCUpdateCondition, without them: their colours stayed 0, 0, 0. Once per save (save.sdsw.colors), at
 * the title, the unlocked patterns whose three colours are still 0 get the game's default ones; colours the
 * player chose are left alone.
 */

// @target amx/mode_title.amx

#include "natives.inc"

forward sdswPatternColors();
public sdswPatternColors()
{
    if (sysGetGlobal("save.sdsw.colors"))
        return 0;
    new unlocked[32];
    sysGetGlobalArray("save.sub.pattern.unlock", unlocked, 32, false);
    new colorSet = worldNewActor();
    actorReadProperties("sub_color_set", colorSet);
    new name[96];
    for (new pattern = 1; pattern < 32; pattern++) {
        if (!unlocked[pattern])
            continue;
        new chosen = 0;
        for (new c = 0; c < 3; c++) {
            strformat(name, sizeof name, false, "save.sub.pattern%d.color%d", pattern, c);
            if (sysGetGlobal(name))
                chosen = 1;
        }
        if (chosen)
            continue;
        new colors[4];
        strformat(name, sizeof name, false, "pattern_%02d", pattern - 1);
        actorGetPropRGB(name, colors, colorSet);
        for (new c = 0; c < 3; c++) {
            strformat(name, sizeof name, false, "save.sub.pattern%d.color%d", pattern, c);
            sysSetGlobal(name, colors[c]);
        }
    }
    actorKill(colorSet);
    sysSetGlobal("save.sdsw.colors", 1);
    sysSetGlobal("mode.savedata.sub", 1);
    return 0;
}

main()
{
}

/* asm
; Start of the title: right after sysDLCUpdateCondition(), where the mod unlocks everything.
.hook 0xdf5c
    .original
    push.c 0
    call @pw_sdswPatternColors
    .return
*/
