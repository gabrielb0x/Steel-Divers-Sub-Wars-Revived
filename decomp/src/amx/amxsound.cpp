// source/amx/amxsound.cpp (amxsound.o): the sound natives of the scripts (natives_Sound, registered by
// amx_SoundInit 0x00171960). Each calls the game's sound manager, DsSubAudioMgr (its one instance at
// 0x005CE4B8; DsSubAudioMgr.cpp — "DsSub": the manager comes from the DS game, Steel Diver). Sounds are
// the ids of the sound archive (romfs:/audiores/sound_data.xml names them: Bgm_TITLE, SE_...).
//
// Reconstructed by hand from decomp/raw/source/amx/amxsound.cpp and the disassembly. Not compilable on its own.

static DsSubAudioMgr *const s_audio = (DsSubAudioMgr *)0x005CE4B8;

// One-shot sounds (Trg_*): skipped while the replay plays, unless asked (the last argument).
static cell n_sndSE(AMX *, const cell *p) { if (!g_world->replaying || p[3]) s_audio->Trg_Se(p[1]); return 0; }            // 0x0032697C
static cell n_sndSEDistance(AMX *, const cell *p) { if (!g_world->replaying || p[4]) s_audio->Trg_Se(p[1]); return 0; }    // 0x003269C8 (no distance)
static cell n_sndSEReplay(AMX *, const cell *p) { s_audio->Trg_Se(p[1]); return 0; }                                      // 0x00326A18
static cell n_sndVoice(AMX *, const cell *p) { s_audio->Trg_Voice(p[1]); return 0; }                                      // 0x00326B9C

// Continuous sounds (Lev_*: "level", kept alive while called every frame), with a Float level.
static cell n_sndLevSE(AMX *, const cell *p) { s_audio->Lev_Se(p[1], amx_ctof(p[2])); return 0; }                         // 0x003268F0
static cell n_sndLevSEDistance(AMX *, const cell *p) { s_audio->Lev_Se(p[1], amx_ctof(p[3]), amx_ctof(p[2])); return 0; }  // 0x00326910
static cell n_sndSonar(AMX *, const cell *p) { s_audio->Lev_Sonar(amx_ctof(p[1])); return 0; }                            // 0x00326A58
static cell n_sndSubCruise(AMX *, const cell *p) { s_audio->Lev_SubmarineCruise(amx_ctof(p[1])); return 0; }              // 0x00326A8C
static cell n_sndSubSpeed(AMX *, const cell *p) { s_audio->Lev_SubmarineSpeed(amx_ctof(p[1])); return 0; }                // 0x00326ADC
static cell n_sndSubEngine(AMX *, const cell *p) { s_audio->Lev_SubmarineEngine(p[1], p[4] != 0); return 0; }             // 0x00326AA8
// 0x003267F4 / 0x00326BB8: an enemy torpedo approaching, the water leak: not during a replay.
static cell n_sndEnemyTorpedoSE(AMX *, const cell *p) { if (!g_world->replaying) s_audio->Lev_EnemyTorpedoSe(p[3]); return 0; }
static cell n_sndWaterLeakSE(AMX *, const cell *p) { if (!g_world->replaying) s_audio->Lev_WaterLeakSe(p[3]); return 0; }

// Music.
static cell n_sndBGMInt(AMX *, const cell *p) { s_audio->Trg_BgmStart(p[1]); return 0; }        // 0x003266EC
static cell n_sndStopBGM(AMX *, const cell *) { s_audio->Trg_BgmStop(); return 0; }              // 0x00326A74
static cell n_sndIsBGM(AMX *, const cell *) { return s_audio->IsBgm(); }                          // 0x003268E4
static cell n_sndExtBgmVolume(AMX *, const cell *p) { s_audio->ExtBgmVolume(amx_ctof(p[1])); return 0; }            // 0x0032683C
static cell n_sndSetMorsePageBgmVolume(AMX *, const cell *p) { s_audio->ExtBgmVolume(amx_ctof(p[1])); return 0; }   // 0x00326A38 (the same)
static cell n_sndTrgStage(AMX *, const cell *p) { s_audio->Trg_Stage(p[1], p[2]); return 0; }   // 0x00326B30
static cell n_sndTrgBattleSpectator(AMX *, const cell *) { s_audio->Trg_BattleSpectator(); return 0; }   // 0x00326B18
static cell n_sndTrgTutorial(AMX *, const cell *) { s_audio->Trg_Tutorial(); return 0; }         // 0x00326B54
static cell n_sndTutorial(AMX *, const cell *p) { if (p[1]) s_audio->Trg_TutorialOn(); else s_audio->Trg_TutorialOff(); return 0; }   // 0x00326B6C
static cell n_sndPauseOn(AMX *, const cell *) { s_audio->Trg_PauseOn(); return 0; }              // 0x00326964
static cell n_sndPauseOff(AMX *, const cell *) { s_audio->Trg_PauseOff(); return 0; }            // 0x0032694C
static cell n_sndPauseExit(AMX *, const cell *) { s_audio->Trg_PauseExit(); return 0; }          // 0x00326934

// The sound banks: sndInit(n) (System::initSound) and sndGroupChange(group): load a group of the archive.
static cell n_sndInit(AMX *, const cell *p) { System::initSound(p[1] & 0xFF); return 0; }         // 0x003268CC
static cell n_sndGroupChange(AMX *, const cell *p) { s_audio->player->dataManager.loadData(p[1]); return 0; }   // 0x00326858

// 0x00326728: sndCalcCameraPan(position[3]): the stereo pan of a sound at a position, from the first active
// renderer's camera: the direction to it, normalised, dotted with the camera's right axis (+0xE8, +0xF0).
static cell n_sndCalcCameraPan(AMX *, const cell *p);

// Left empty: sndIcebergSE (0x00326884, its sound manager side CalcDsSubAudioMgr_Iceberg is empty too: the
// icebergs of the DS game), sndBattleBGMInt (0x00326708), sndSubmarinePosition (0x00326AF8).
static cell n_sndIcebergSE(AMX *, const cell *) { return 0; }
static cell n_sndBattleBGMInt(AMX *, const cell *) { return 0; }
static cell n_sndSubmarinePosition(AMX *, const cell *) { return 0; }
