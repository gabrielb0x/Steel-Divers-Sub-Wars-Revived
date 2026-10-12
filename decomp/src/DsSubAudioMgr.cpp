// source/DsSubAudioMgr.cpp (DsSubAudioMgr.o): the game's sound manager, on Nintendo's eau / nw::snd. One
// instance (0x005CE4B8); the scripts reach it through the sound natives (amx/amxsound.cpp). "DsSub": it comes
// from Steel Diver on the DS, whose names it keeps: the single-player missions' music (Bgm_Mission1_1...
// Bgm_Mission7_BOSS), the sea battle's ships, "Taisen" (対戦, versus) for the multiplayer battle music.
//
// Reconstructed by hand from decomp/raw/source/DsSubAudioMgr.cpp and the disassembly. Not compilable on its
// own. The sound names are the developers' own, from the SoundMaker header shipped in the RomFS
// (audiores/sound_data.csid): Bgm_* streams, SE_Trg_* one-shot effects, SE_Lev_* "level" effects that last
// while they are asked every frame (LevelSe), Voice_A_* / Voice_B_* the crew's voices, PLAYER_* the players.
//
// Every entry point first checks `soundOff` (+0x809), which nothing ever sets: a switch of the DS game.
// The BasicSound calls (volume, fade) take float arguments the decompiler lost; the volumes below are the
// manager's own targets.

class DsSubAudioMgr : public eau::AudioMgr {        // vtable 0x0037642C
	nw::snd::SoundArchivePlayer *player;            // +0x008
	u8 resourceSet;                                 // +0x021 Trg_SoundResourceSet
	u8 mode;                                        // +0x022
	f32 trackVolume[4];                             // +0x024 the 4 tracks of the menus' music (below)
	f32 jingleVolume, fanfareVolume;                // +0x034, +0x038
	DsSubAudioComponents components;                // +0x03C (eau::AudioSystem...)
	LevelSe levelSe;                                // +0x51C 0x1E4 bytes: the SE_Lev_* sounds of the frame
	nw::snd::SoundHandle bgm[4];                    // +0x700 the music; [1..3] the menus' extra tracks
	nw::snd::SoundHandle ranking, fanfare;          // +0x710 Bgm_RANKING, +0x714 Bgm_FANFARE_EXPERT_OPEN
	nw::snd::SoundHandle se, voice, pauseSe;        // +0x718, +0x71C, +0x720
	bool paused, tutorial;                          // +0x724, +0x725
	int tutorialTimer;                              // +0x728 (200)
	bool bgmOnly;                                   // +0x72C the title and the ending: effects and voices muted
	u32 currentBgm, lastSe;                         // +0x730, +0x734
	f32 sonarCountdown, sonarStep, sonarVolume;     // +0x738, +0x73C, +0x740
	int pauseExitFrames;                            // +0x744
	f32 subSpeed;                                   // +0x748 Lev_SubmarineSpeed (stored, unused)
	int cooldown[11];                               // +0x74C..+0x774 frames before an effect may play again
	int resultFade, resultFadeDelay;                // +0x784, +0x788 after a mission's result, effects fade out
	f32 resultFadeRate;                             // +0x78C
	int sonarPings;                                 // +0x790
	u32 engineSe; f32 engineLevel, enginePitch; bool engineOn;   // +0x794..+0x7A0 Lev_SubmarineEngine
	f32 cruiseLevel;                                // +0x7B0
	int nearFrames; bool near;                      // +0x7B4, +0x7B8 an enemy within 1000 (sonar)
	bool leakThisFrame, leakSounding, leakVoiceSaid;   // +0x7B9..+0x7BB
	u32 voiceA, voiceB, queuedA, queuedB;           // +0x7EC..+0x7F8 two voice channels, one queued each
	int voiceATimer, voiceBTimer;                   // +0x7FC, +0x800 50 frames per voice
	int engineRamp;                                 // +0x804 0..30
	bool calcStopped, soundOff;                     // +0x808, +0x809
	bool tracksPrepared; int tracksState;           // +0x80A, +0x80C
	bool bgmPrepared, finalized, finalizeAsked;     // +0x810..+0x812
	int finalizeFrames;                             // +0x814
	u32 delayedSe[8]; int delayedFrames[8];         // +0x818, +0x838
	bool bgmLocked;                                 // +0x858
	int stage, stageVariant;                        // +0x85C, +0x860 Trg_Stage
	bool insideSub;                                 // +0x868
	int criticalHits;                               // +0x86C
	int stageFrames;                                // +0x870 not counting the pause
	int trackFade[4];                               // +0x87C fade frames of each track
	f32 extBgmVolume;                               // +0x894 ExtBgmVolume
	int trackAge[6];                                // +0x898..+0x8AC frames since each music started
	u32 nextBgm; int nextBgmDelay;                  // +0x8B0, +0x8B4 a music started after a fade
	u32 heldLevelSe;                                // +0x8B8
	nn::os::CriticalSection lock;                   // +0x8C0 (with the sound thread)
	bool mutedVoices, bgmBlocked, volumesDirty;     // +0x8DC, +0x8DD, +0x8DF
	int engineStep; f32 engineLast;                 // +0x8E0, +0x8E4
	bool battleTrigger; int battleFrames;           // +0x8E8, +0x8EC
	int stageTime;                                  // +0x8F0 up to 30000
	bool limitSaid[4]; int limitCount[4];           // +0x8F4.. the engine's limits, voiced every few times
	int decals;                                     // +0x90C
	bool emergency, surfaced, playedStageBgm, exitedPause;   // +0x910..+0x913
	int spectator;                                  // +0x914
	bool battleFaded;                               // +0x918
	f32 seVolume;                                   // +0x920 (0.5 while SE_Trg_... "quiet" is on)
};

// ---- life cycle ------------------------------------------------------------------------------------------

// 0x0017D610: the components, the LevelSe (its 48 level sounds, 10 at a time), the lock, then StageInit.
DsSubAudioMgr::DsSubAudioMgr();
// 0x0017D6DC: detaches the 9 handles, then the bases.
DsSubAudioMgr::~DsSubAudioMgr();

// 0x00109108: after a sound group change: the sound heap emptied, the group 0x06000000 loaded (resource sets
// 0 and 1), the state reset, surround on, the master volume set.
void DsSubAudioMgr::Trg_Init()
{
	player->soundHeap.Clear();
	if (resourceSet < 2)
		player->dataManager.loadData(0x06000000, -1);
	bgmLocked = finalized = finalizeAsked = false;
	finalizeFrames = 0;
	calcStopped = soundOff = false;
	currentBgm = 0;
	stage = stageVariant = 0;
	playedStageBgm = false;
	StageInit();
	levelSe.Init(this);
	nn::snd::SetSurroundDepth(1.0f);
	nn::snd::SetSurroundSpeakerPosition(0);
	if (se.sound) se.sound->panCurve = 0;       // +0xD0
	if (voice.sound) voice.sound->panCurve = 0;
	nw::snd::HardwareManager::SetMasterVolume(1.0f, 0);
}

void DsSubAudioMgr::Trg_InitCore(u32 core) { if (core < 2) components.audioSystem.setSoundThreadCore(core); }   // 0x001090B4
void DsSubAudioMgr::Trg_SoundResourceSet(int set) { resourceSet = set; if (set == 0 || set == 1) components.Init(set); }   // 0x001090D8
void DsSubAudioMgr::Trg_CalcStop() { calcStopped = true; }      // 0x001090A8
void DsSubAudioMgr::Trg_CalcStart() { calcStopped = false; }    // 0x001090CC

// 0x00116618 / 0x0010908C: a finalize is asked of the player; two frames later IsFinalized says yes, once.
void DsSubAudioMgr::finalizeRequest() { finalizeAsked = true; player->requestFinalize(); }
bool DsSubAudioMgr::IsFinalized() { bool f = finalized; finalized = false; return f; }

// 0x002455B8: every per-stage state back to its start (cooldowns, voices, fades of 30 frames, sonar).
void DsSubAudioMgr::StageInit();

// ---- every frame -----------------------------------------------------------------------------------------

// 0x002457E8: the eau manager's own update under the lock (unless stopped), a stream kept alive a few
// frames (+0x91C), then CalcDsSubAudioMgr, then the lock released.
void DsSubAudioMgr::CalcUpdate();

// 0x00111474 CalcSceneInit runs into 0x00111478 CalcDsSubAudioMgr:
void DsSubAudioMgr::CalcDsSubAudioMgr()
{
	if (soundOff)
		return;
	if (finalizeAsked && ++finalizeFrames == 2) {
		finalized = true;
		finalizeAsked = false;
		finalizeFrames = 0;
	}
	if (calcStopped)
		return;
	levelSe.Framework(paused, tutorial);         // the SE_Lev_* asked this frame play, the others stop
	CalcDsSubAudioMgr_MultiStreamBgm_IsPrepared();
	if (bgm[0].sound && bgm[0].sound->IsPrepared() && bgmPrepared) {
		bgm[0].sound->StartPrepared();
		bgmPrepared = false;
	}
	if (pauseExitFrames != 0 && ++pauseExitFrames == 2) {     // leaving the pause takes 2 frames
		paused = false;
		pauseExitFrames = 0;
	}
	CalcDsSubAudioMgr_AfterGameJudgeSeCutCalc();
	CalcDsSubAudioMgr_VolumeSet();
	if (cooldown[0] != 0 && ++cooldown[0] > 69)    // Voice_B_001 at most every 70 frames
		cooldown[0] = 0;
	CalcDsSubAudioMgr_TrgSeRestriction();
	CalcDsSubAudioMgr_WaterLeak();
	// The two voice channels: 50 frames per voice, then the queued one.
	if (voiceATimer != 0 && ++voiceATimer == 50) {
		voiceATimer = 0;
		if (queuedA) Trg_Voice(queuedA);
		queuedA = 0;
	}
	if (voiceBTimer != 0 && ++voiceBTimer == 50) {
		voiceBTimer = 0;
		if (queuedB) Trg_Voice(queuedB);
		queuedB = 0;
	}
	if (currentBgm == Bgm_SUCCESS_LAST || currentBgm == Bgm_OVER)
		*(f32 *)((u8 *)this + 0x878) = 0.7f;
	if (!paused)
		for (int &age : trackAge) if (age) age++;
	// A music asked to start after the current one faded (the bosses, Bgm_OVER): when its delay ends.
	if (nextBgmDelay != 0 && !paused && --nextBgmDelay == 1) {
		bgm[0].Stop(0);
		player->StartSound(&bgm[0], nextBgm);
		trackVolume[0] = 1;
		extBgmVolume = 1;
		volumesDirty = true;
		trackFade[0] = 0;
		bgmOnly = false;
		currentBgm = nextBgm;
		trackAge[0] = 1;
		resultFade = 0;
	}
	if (heldLevelSe != 0)
		Lev_Se_Private(heldLevelSe);
	if (!paused) {
		for (int i = 0; i < 8; i++)              // the delayed effects (the ships' launches...)
			if (delayedFrames[i] != 0 && --delayedFrames[i] == 0 && delayedSe[i] != 0) {
				Trg_Se(delayedSe[i]);
				delayedSe[i] = 0;
			}
		stageFrames++;
	}
	CalcDsSubAudioMgr_Iceberg();
	// +0x7BC..+0x7E8: four "nearest" slots reset to 65535 each frame (filled by nobody in Sub Wars).
	CalcDsSubAudioMgr_TaisenBgm();
	if (!paused && stageTime < 30000)
		stageTime++;
}

void DsSubAudioMgr::CalcDsSubAudioMgr_Iceberg() {}   // 0x0011B750: empty (the DS game's icebergs)

// 0x0011B7E0: the multiplayer battle music. A trigger (an incoming torpedo, Lev_Se_Private, once the stage
// is 1050 frames old) starts the stage's Bgm_MultiPlay<N>_Battle; it plays on for 450 frames (7.5 s) after
// the last trigger, then fades out over 90 frames; a new trigger fades it back in.
void DsSubAudioMgr::CalcDsSubAudioMgr_TaisenBgm()
{
	static const u32 music[] = { Bgm_MultiPlay1_Battle, Bgm_MultiPlay2_Battle, 0, Bgm_MultiPlay3_Battle,
		Bgm_MultiPlay4_Battle, Bgm_MultiPlay5_Battle, Bgm_MultiPlay6_Battle, Bgm_MultiPlay7_Battle,
		Bgm_MultiPlay8_Battle, Bgm_MultiPlay9_Battle };      // stages 10..19 (none for 12)
	if (battleTrigger) {
		if (++battleFrames == 1 && !battleFaded) {
			if (stage >= 10 && stage <= 19 && music[stage - 10])
				Trg_BgmStart(music[stage - 10]);
		} else {
			extBgmVolume = 1;
			volumesDirty = true;
			battleFrames = 1;
			trackFade[0] = 90;
			battleFaded = false;
		}
	} else if (battleFrames != 0 && battleFrames < 450 && ++battleFrames == 450
	           && currentBgm >= Bgm_MultiPlay1_Battle && currentBgm <= Bgm_MultiPlay9_Battle) {
		extBgmVolume = 0;
		volumesDirty = true;
		trackFade[0] = 90;
		battleFaded = true;
	}
	battleTrigger = false;
}

// 0x0011B9E0: the tracks' volumes when they changed; paused, every effect player is paused (PLAYER_TRG_SE,
// PLAYER_VOICE, PLAYER_VOICE_CAP, PLAYER_ENGINE_SE, PLAYER_BUBBLE_SE, PLAYER_LEVEL_SE), else resumed. During
// the result's fade nothing changes.
void DsSubAudioMgr::CalcDsSubAudioMgr_VolumeSet()
{
	static const u32 players[] = { PLAYER_TRG_SE, PLAYER_VOICE, PLAYER_VOICE_CAP, PLAYER_ENGINE_SE,
		PLAYER_BUBBLE_SE, PLAYER_LEVEL_SE };
	if (!paused && resultFade != 0)
		return;
	if (volumesDirty) {
		for (int i = 0; i < 4; i++)
			if (bgm[i].sound) bgm[i].sound->SetVolume(trackVolume[i] * extBgmVolume, trackFade[i]);
		if (!paused) {
			if (ranking.sound) ranking.sound->SetVolume(jingleVolume, 0);
			if (fanfare.sound) fanfare.sound->SetVolume(fanfareVolume, 0);
		}
		volumesDirty = false;
	}
	for (u32 p : players)
		player->GetSoundPlayer(p)->PauseAllSound(paused, 1);
}

// 0x0011BC6C: the water leak: its alarm (SE_Lev_emergency) while leaking, SE_Trg_WaterLeakStop when it ends
// inside the submarine, and the crew's Voice_B_001 once per leak.
void DsSubAudioMgr::CalcDsSubAudioMgr_WaterLeak()
{
	if (leakThisFrame) {
		Lev_Se_Private(SE_Lev_emergency);
		leakSounding = true;
	} else if (leakSounding) {
		if (insideSub)
			Trg_Se(SE_Trg_WaterLeakStop);
		leakSounding = false;
	}
	if (leakThisFrame && !leakVoiceSaid) {
		Trg_Voice(Voice_B_001);
		leakVoiceSaid = true;
	} else if (!leakThisFrame) {
		leakVoiceSaid = false;
	}
	leakThisFrame = false;
}

// 0x0011BD70: the cooldowns of the effects that must not pile up (Trg_Se sets them to 1): the panel lever
// 3 frames, the rotate levers 5 and 6, the explosion and the torpedo loading 2, "air insufficient" 10, the
// crush 8 (and a 100-frame one behind it).
void DsSubAudioMgr::CalcDsSubAudioMgr_TrgSeRestriction();

// 0x0011BEC0: after a mission's result (Bgm_SUCCESS_*), effects keep their volume for 200 frames, then fade
// by 0.5 % a frame; the volume of every effect player follows.
void DsSubAudioMgr::CalcDsSubAudioMgr_AfterGameJudgeSeCutCalc()
{
	f32 volume = 1;
	if (resultFade != 0) {
		int t = ++resultFade;
		if (t >= resultFadeDelay) {
			volume = 1 - (t - resultFadeDelay) * resultFadeRate;
			if (volume <= 0)
				resultFade--;                   // stays at the silent frame
		}
	}
	for (u32 p : { PLAYER_TRG_SE, PLAYER_ENGINE_SE, PLAYER_BUBBLE_SE, PLAYER_LEVEL_SE, PLAYER_VOICE,
	               PLAYER_VOICE_CAP, PLAYER_SLIDE_CLICK_SE })
		player->GetSoundPlayer(p)->SetVolume(std::max(volume, 0.0f) * seVolume);
}

// 0x0011C004: the menus' three extra tracks start together once all three are prepared.
void DsSubAudioMgr::CalcDsSubAudioMgr_MultiStreamBgm_IsPrepared()
{
	if (bgm[1].sound && bgm[1].sound->IsPrepared() && bgm[2].sound && bgm[2].sound->IsPrepared()
	    && bgm[3].sound && bgm[3].sound->IsPrepared() && tracksPrepared && tracksState != 1) {
		for (int i = 1; i < 4; i++)
			bgm[i].sound->StartPrepared();
		tracksPrepared = false;
		tracksState = 0;
	}
}

// ---- music -----------------------------------------------------------------------------------------------
// The menus' music is one piece in four synchronised streams: Bgm_MAIN_MENU and the extra tracks prepared by
// Trg_BgmStart1..3 (0x002328F0, 0x00232884, 0x00232818: each stops its handle and prepares its stream). A
// screen does not change the music, it crossfades the tracks (trackVolume[]): main menu, submarine select
// (tracks 1 and 2), options, shop, the free-to-play screen (Bgm_F2P)... `playedStageBgm` (a stage's music
// was heard since the title) chooses between going back to the layered piece and restarting it.

// 0x00236C34
void DsSubAudioMgr::Trg_BgmStart(u32 id)
{
	if (soundOff || bgmBlocked || bgmLocked)
		return;
	exitedPause = false;
	if (id == Bgm_SUCCESS_PERISCOPE && stage == 5)
		id = Bgm_SUCCESS_LAST;                  // the last mission's success
	else if (id >= Bgm_SELECTSEABATTLEforTUTORIAL && id <= Bgm_MultiPlay9_Battle)
		playedStageBgm = true;
	if (id == Bgm_TITLE)
		playedStageBgm = false;
	volumesDirty = true;
	if (id >= Bgm_MultiPlay1_Battle && id <= Bgm_MultiPlay9_Battle)
		spectator = 0;
	switch (id) {
	case Bgm_TITLE:                             // the extra tracks stop; only music plays
		mutedVoices = false;
		bgmOnly = true;
		paused = false;
		for (int i = 1; i < 4; i++) bgm[i].Stop(1);
		break;
	case Bgm_ENDING:
		bgmOnly = true;
		break;
	case Bgm_MAIN_MENU:                         // back to the layered piece, or (re)start its four streams
	case Bgm_SUBMARINE_SELECT:
	case Bgm_SELECT_OPTION:
	case Bgm_Shop:
	case Bgm_F2P:
		// crossfades of trackVolume[0..3] over 10..30 frames; see the raw switch for each screen's mix
		break;
	case Bgm_FANFARE_EXPERT_OPEN:               // over the music: the music at 20 %
		player->StartSound(&fanfare, id);
		jingleVolume = 0.2f;
		fanfareVolume = 1;
		trackAge[5] = 1;
		bgmOnly = false;
		insideSub = true;
		currentBgm = id;
		return;
	case Bgm_DrawBattle:
		if (currentBgm == Bgm_BattleKansen)
			return;
		// fall through
	case Bgm_WinBattle:
	case Bgm_LoseBattle:
		battleTrigger = false;
		break;                                  // restarted below
	case Bgm_BattleKansen:                      // not over a win or a loss already playing
		battleTrigger = false;
		if (currentBgm == Bgm_WinBattle || currentBgm == Bgm_LoseBattle)
			return;
		break;
	case Bgm_SUCCESS_PERISCOPE:
	case Bgm_SUCCESS_LAST:                      // and the effects fade out after 200 frames (0.5 %/frame)
		bgm[0].Stop(0);
		player->StartSound(&bgm[0], id);
		trackVolume[0] = extBgmVolume = 1;
		resultFadeDelay = 200;
		currentBgm = id;
		trackAge[0] = 1;
		resultFadeRate = 0.005f;
		resultFade = 1;
		return;
	case Bgm_OVER:                              // after 30 frames, everything stopped now
		nextBgmDelay = 30;
		nextBgm = id;
		trackVolume[0] = 0;
		trackFade[0] = 1;
		for (auto &h : bgm) h.Stop(1);
		return;
	case Bgm_RANKING:
		player->StartSound(&ranking, id);
		jingleVolume = 1;
		currentBgm = id;
		trackAge[4] = 1;
		resultFade = 0;
		return;
	// The missions: variant 2 or 3 of the music by Trg_Stage's second number.
	case Bgm_Mission1_1: case Bgm_Mission2_1: case Bgm_Mission3_1: case Bgm_Mission4_1:
	case Bgm_Mission5_1: case Bgm_Mission6_1: case Bgm_Mission7_1:
		if (stageVariant == 2 || stageVariant == 3)
			id += stageVariant - 1;
		break;
	// The bosses and the gate: the current music fades out, the new one starts after a delay.
	case Bgm_Mission3_GATE:  nextBgmDelay = 120; trackVolume[0] = 0; trackFade[0] = 25;  nextBgm = id; return;
	case Bgm_Mission3_BOSS:  nextBgmDelay = 90;  trackVolume[0] = 0; trackFade[0] = 120; nextBgm = id; return;
	case Bgm_Mission5_BOSS:  Trg_Voice(Voice_B_005);
	                         nextBgmDelay = 120; trackVolume[0] = 0; trackFade[0] = 150; nextBgm = id; return;
	case Bgm_Mission6_BOSS:  nextBgmDelay = 210; trackVolume[0] = 0; trackFade[0] = 180; nextBgm = id; return;
	case Bgm_Mission7_BOSS:  if (currentBgm == id) return;
	                         nextBgmDelay = 120; trackVolume[0] = 0; trackFade[0] = 150; nextBgm = id; return;
	case Bgm_MultiPlay1_Battle: case Bgm_MultiPlay2_Battle: case Bgm_MultiPlay3_Battle:
	case Bgm_MultiPlay4_Battle: case Bgm_MultiPlay5_Battle: case Bgm_MultiPlay6_Battle:
	case Bgm_MultiPlay7_Battle: case Bgm_MultiPlay8_Battle: case Bgm_MultiPlay9_Battle:
		if (currentBgm == id)
			return;
		currentBgm = id;
		break;
	}
	// Any other music: everything stops, the new one starts at full volume.
	for (auto &h : bgm) h.Stop(0);
	player->StartSound(&bgm[0], id);
	*(int *)((u8 *)this + 0x91C) = 20;
	trackVolume[0] = extBgmVolume = 1;
	trackFade[0] = 0;
	bgmOnly = false;
	resultFade = 0;
	trackAge[0] = 1;
	currentBgm = id;
}

// 0x0017C2AC: fades the music out by kind: the results and the ending in 12 frames, the battle results in
// 25, the main menu's four tracks in 15, the multiplayer battle music in 120, Bgm_F2P stopped in 190, the
// others stopped in 30; the title and Bgm_OVER keep playing. The delayed effects and voices are dropped.
void DsSubAudioMgr::Trg_BgmStop();

// 0x0017D160
bool DsSubAudioMgr::IsBgm() { return ranking.sound || bgm[0].sound || bgm[1].sound || bgm[2].sound || bgm[3].sound; }

void DsSubAudioMgr::ExtBgmVolume(f32 v) { if (!soundOff) { extBgmVolume = v; volumesDirty = true; } }   // 0x0017C70C

// 0x0017D5DC: a new stage (its number, its music variant).
void DsSubAudioMgr::Trg_Stage(int s, int variant) { if (!soundOff) { StageInit(); stage = s; stageVariant = variant; } }

// 0x0017D12C: a spectator of a multiplayer battle (stages 10..19) hears Bgm_BattleKansen.
void DsSubAudioMgr::Trg_BattleSpectator()
{
	if (!soundOff && stage >= 10 && stage < 20) {
		spectator = 1;
		Trg_BgmStart(Bgm_BattleKansen);
	}
}

// ---- pause, tutorial -------------------------------------------------------------------------------------

// 0x0017C64C: the music pauses (3-frame fade), SE_Trg_pause_on, the voice silenced, the effect players
// paused at the next frame (VolumeSet).
void DsSubAudioMgr::Trg_PauseOn();
// 0x0017C72C: the reverse, with SE_Trg_pause_off (not while leaving the pause).
void DsSubAudioMgr::Trg_PauseOff();
// 0x0017C878: leaving to the menu from the pause: the music and every effect stopped, SE_Trg_pause_exit,
// and the voices, engine and level sounds muted until the next music (exitedPause).
void DsSubAudioMgr::Trg_PauseExit();

void DsSubAudioMgr::Trg_TutorialOn() { if (!soundOff) tutorial = true; }     // 0x0017CA38
void DsSubAudioMgr::Trg_TutorialOff() { if (!soundOff) tutorial = false; }   // 0x0017CB2C
// 0x0017C830: the tutorial's start (the level sounds' tutorial mode for 200 frames).
void DsSubAudioMgr::Trg_Tutorial() { if (!soundOff) { tutorial = true; tutorialTimer = 200; } }

// ---- effects ---------------------------------------------------------------------------------------------

// 0x0017D274 runs into 0x0023E070. One-shot effects, with the game's rules:
//   - a sound 10000 or more away (s1) is not played;
//   - ids 0x0100008C..0x010000AB play their voice and the crew's beep (SE_Trg_decide_crew_beep);
//   - SE_Trg_ShipSurface / SE_Trg_ShipDive set `surfaced` (the level sounds' under-water variants);
//   - SE_Trg_Doc_Weld only in the submarine select's dock;
//   - SE_Trg_GetDecal starts Bgm_Mission3_GATE in mission 3, Bgm_Mission6_BOSS at the third in stage 7;
//   - paused or bgmOnly, only the menu sounds play (save, levers, cursor, attention, periscope start);
//   - the sea battle's ships (SE_Trg_BattleShip_*) play their "_real" sound 10 or 15 frames later;
//   - SE_Trg_CriticalHit escalates: CriticalHit, 1, 2, 3, then 4 for every next one, with Voice_B_006;
//   - SEQ_RepairItemGet: Voice_A_016; others give Voice_A_002/009/010;
//   - the cooldowns above; explosions are panned by s0 (half of its magnitude);
//   - the pause sounds use their own handle, the others share one (pan curve and pan set).
// SEQ_* sequences (SEQ_HANABI, SEQ_RegularEnlistment, SEQ_MorseCodeSend...) play as they are.
void DsSubAudioMgr::Trg_Se(u32 id, f32 pan, f32 distance);

// 0x0023E7DC: the level sounds (LevelSe::SeCall) with their substitutions: the waterfall and the water pump
// under water when not surfaced; no ship wake in stage 6; the torpedo alarms (SE_Lev_emergency_NormalTorpedo
// / _HormingTorpedo) also sound SE_Lev_PeriscopeMode_EnemyTorpedo and trigger the battle music once the
// stage is 1050 frames old; SE_Lev_SubmarineInside
// marks the inside of the submarine (not in the main menu). SE_Lev_MorseCode always plays; the rest not
// after the pause was left, and the alarms not over the final results.
void DsSubAudioMgr::Lev_Se_Private(u32 id);

void DsSubAudioMgr::Lev_Se(u32 id) { if (!soundOff) Lev_Se_Private(id); }    // 0x0017D1C8 (and 0x0013FFC8)
// 0x0017D1F4: the same, unless 10000 or more away.
void DsSubAudioMgr::Lev_Se(u32 id, f32 level, f32 distance) { if (!soundOff && (distance == 0 || distance <= 10000)) Lev_Se_Private(id); }

// 0x0017CA4C / 0x0017CB3C: the leak's sound by its strength 0..3 (SE_Lev_WaterLeak0..3), the enemy torpedo's
// by its distance 0..3 (SE_Lev_PeriscopeMode_EnemyTorpedo0..3).
void DsSubAudioMgr::Lev_WaterLeakSe(int n)
{
	if (soundOff)
		return;
	if (n >= 0 && n <= 3)
		Lev_Se_Private(SE_Lev_WaterLeak0 + n);
	leakThisFrame = true;
}
void DsSubAudioMgr::Lev_EnemyTorpedoSe(int n) { if (!soundOff && n >= 0 && n <= 3) Lev_Se_Private(SE_Lev_PeriscopeMode_EnemyTorpedo0 + n); }

void DsSubAudioMgr::Lev_SubmarineSpeed(f32 v) { if (!soundOff) subSpeed = v; }   // 0x0017CBF8
// 0x0017CC0C: the sound of cruising at the surface.
void DsSubAudioMgr::Lev_SubmarineCruise(f32 level)
{
	if (soundOff)
		return;
	cruiseLevel = level;
	if (!paused && !bgmOnly) {
		surfaced = true;
		levelSe.SeCall(SE_Lev_CruiseTopWater);
	}
}

// 0x0017CCF4: the engine (sound `id`, its throttle and depth rate in s0/s1). At full throttle forward or
// back (±4.995) and full dive or rise (±5) the crew says so (Voice_A_003, _004, _008, _012), every 4th or
// 2nd time; the throttle's sound moves by 0.13875 at most per frame; a ramp of 30 frames follows `on`. A
// spectator does not hear SE_Lev_submarine_engine_b.
void DsSubAudioMgr::Lev_SubmarineEngine(u32 id, f32 throttle, f32 depthRate, bool on);

// 0x0017D290: the sonar's ping, faster as the nearest enemy (s0) comes closer: the distance, clamped to
// 100..3000, is consumed by a step per frame that depends on it (30 under 250, then 34, 38, 43, 48, 53, 58
// up to 1750, 57, 56, 55 up to 2500, 19 beyond). An enemy within 1000 for 90 frames, or within 1500 after
// that, makes the ping louder (1.0 instead of 0.6). Silent on the title, the final success, and for the
// first 330 frames of a stage. Every third ping is quieter (an echo).
void DsSubAudioMgr::Lev_Sonar(f32 distance);

// 0x0023EB24: two voice channels (A below Voice_B_001, B from it), one voice at a time each, 50 frames,
// one queued. Not while paused, muted or bgmOnly. Voice_B_010 becomes Voice_B_010_2 during an alarm;
// Voice_B_001 at most every 70 frames. A leftover: the id 0x0100003E is still tested as a voice (it queues
// Bgm_SUCCESS_PERISCOPE 120 frames later in modes 5 and 6), but in Sub Wars' archive it is
// Bgm_MultiPlay9_Battle, which nothing passes to Trg_Voice: an id of the DS game, renumbered.
void DsSubAudioMgr::Trg_Voice(u32 id);

// eau::AudioMgr's hooks, empty: 0x002DC8E0 preInitialize_, 0x002DC8E4 postInitialize_, 0x002DC8E8 preCalc_,
// 0x002DC8EC postCalc_. 0x002EF118 LevelSe::LEVEL_SE: the constructor of one of its 48 slots.
// 0x00312A84 __sti___17_DsSubAudioMgr_cpp: the instance's construction.
