// source/fader.cpp (fader.o) and source/icons.cpp (icons.o): the screen fades, and the icons drawn over
// everything: "saving" (top screen, with a tip while loading) and the HOME button's "not now" sign
// (bottom screen).
//
// Reconstructed by hand from decomp/raw/source/{fader,icons}.cpp and the disassembly. Not compilable on its
// own.

// ---- fader.cpp -----------------------------------------------------------------------------------------

enum FadeMode { FADE_NONE, FADE_IN, FADE_OUT, FADE_FLASH };

static u8 s_alpha;                      // 0x0038DFB8 of the black quad (0: nothing drawn)
static float s_progress;                // 0x0038DFBC 0..1
static FadeMode s_mode;                 // 0x0038DFC0
// A full-screen quad (two triangles, -1..1), shaders/fader.shbin, the alpha in the combiner's constant
// colour (0x0043623D); the commands are built once from nn::gr objects (0x00423124..0x00436240).

// 0x0010297C: the shader loaded into the system stock, the quad's six vertices (setVertex 0x0024ECE8).
void Fader::init();

// 0x00102BE4, every frame: fading in takes 10 frames (alpha 255 -> 0), fading out 10 (0 -> 255), a flash 5
// (black at once, then clearing over the last half).
void Fader::update()
{
	float t = s_progress + 0.1f;
	switch (s_mode) {
	case FADE_IN:
		if (t < 1.0f) {
			s_progress = t;
			s_alpha = (u8)((1.0f - t) * 255.0f);
			return;
		}
		break;
	case FADE_OUT:
		if (t < 1.0f) {
			s_progress = t;
			s_alpha = (u8)(t * 255.0f);
		} else {
			s_alpha = 255;
			s_progress = 1.0f;
			s_mode = FADE_NONE;
		}
		return;
	case FADE_FLASH:
		s_progress += 0.2f;
		if (s_progress < 1.0f) {
			s_alpha = (u8)(min(1.0f, 2.0f - s_progress * 2.0f) * 255.0f);
			return;
		}
		break;
	default:
		return;
	}
	s_mode = FADE_NONE;
	s_progress = 1.0f;
	s_alpha = 0;
}

// 0x00253428: the quad over the screen, when it is not transparent (a flash is not drawn on screen 0).
void Fader::draw(int screen);

// 0x002540B0: a new fade, unless it is the one running, or a fade out of a screen already black.
void Fader::startFade(FadeMode mode)
{
	if (mode == FADE_OUT && s_alpha == 255)
		return;
	if (mode != s_mode) {
		s_progress = 0;
		s_mode = mode;
	}
}

void Fader::blackout() { s_alpha = 255; }                    // 0x002538E4
bool Fader::isBlackout() { return s_alpha == 255; }          // 0x002E3104
bool Fader::isFading() { return s_mode != FADE_NONE; }       // 0x002E3124

// ---- icons.cpp -----------------------------------------------------------------------------------------

static bool s_adviceShown;              // 0x0038E440 a tip is shown with the loading icon
static Renderer *s_top, *s_bottom;      // 0x0038E444, 0x0038E448
static Layout *s_saving;                // 0x0038E44C layout "saving_u" (top screen)
static LayoutAnim *s_savingOn, *s_savingOff;   // 0x0038E450, 0x0038E454 "saving_anm_on/off" of "Null_saving"
static Layout *s_homeSign;              // 0x0038E458 layout "HomeNixSign" (bottom screen)
static LayoutAnim *s_homeSignAnim;      // 0x0038E45C "InOut"
static u32 s_homeSignFrames;            // 0x0038E460 frames left of the sign's animation
static int s_advice;                    // 0x0038E464 1..25: the tip shown

// 0x00102D60
void Icons::init()
{
	s_top = Renderer::getRenderer(1);
	s_bottom = Renderer::getRenderer(2);
	s_saving = new Layout();
	s_saving->load("saving_u", s_top->layoutHeap, true, false);
	s_savingOn = s_saving->loadAnim("Null_saving", "saving_anm_on");
	s_savingOff = s_saving->loadAnim("Null_saving", "saving_anm_off");
	s_homeSign = new Layout();
	s_homeSign->load("HomeNixSign", s_bottom->layoutHeap, true, false);
	s_homeSignAnim = s_homeSign->loadAnim("", "InOut");             // the root pane
	if (s_homeSignFrames != 0)
		s_homeSignFrames = 1;
}

// 0x00102E8C: the sign's animation counts down; when it ends, the HOME press is forgotten.
void Icons::update()
{
	s_saving->animate();
	s_saving->update(s_top);
	if (s_homeSignFrames != 0) {
		s_homeSign->animate();
		s_homeSign->update(s_bottom);
		if (--s_homeSignFrames == 0)
			nn::applet::CTR::ClearHomeButtonState();
	}
}

// 0x0024D2C4: HOME was pressed where the game cannot go to the HOME Menu: the sign, for its animation's length.
void Icons::showHomeLock()
{
	if (nn::applet::CTR::IsExpectedToProcessHomeButton() && s_homeSignFrames == 0) {
		s_homeSignAnim->rewind();
		s_homeSignFrames = (u32)s_homeSignAnim->length();
	}
}

bool Icons::isHomeLockShowing() { return s_homeSignFrames != 0; }   // 0x0010CCD4

// 0x002E3380: a tip (1..25) at random, unless the tip pane is showing.
void Icons::chooseAdvice()
{
	if (!s_saving->findPane("n_advice")->visible)
		s_advice = rand() % 25 + 1;
}

// 0x002E31E0: the "saving" icon; withAdvice: with a tip, "advice_title01" ("Battle Tips!") and
// "advice_textNN" (the 25 tips of the texts).
void Icons::showLoading(bool withAdvice)
{
	if (withAdvice) {
		char title[32], text[32];
		sprintf(title, "advice_title%02d", 1);
		sprintf(text, "advice_text%02d", s_advice);
		TextStyle t = TextData::find(title, true);
		if (t.text) {
			s_saving->replaceStyle("text_titlea01", &t);
			s_saving->replaceString("text_titlea01", t.text, true);
		}
		t = TextData::find(text, true);
		if (t.text) {
			s_saving->replaceStyle("text_advice01", &t);
			s_saving->replaceString("text_advice01", t.text, true);
		}
		s_saving->setPaneVisibility(s_saving->findPane("n_advice"), true);
	}
	s_savingOff->stop();
	s_savingOn->play();
}

// 0x002E3160
void Icons::hideLoading()
{
	if (s_adviceShown)
		s_saving->setPaneVisibility(s_saving->findPane("n_advice"), false);
	s_savingOn->stop();
	s_savingOff->play();
}

// 0x00102CF8 / 0x002533BC: the sign on the bottom screen; the saving icon on the top one, per eye.
void Icons::draw(Renderer *r) { Layout::initGX(); Layout::setupCamera(r); Layout::startDraw(r, 0, 0); s_homeSign->draw(r, 0); Layout::endDraw(r, 0); nngxFlush3DCommand(); }
void Icons::drawStereo(Renderer *r, int eye) { Layout::initGX(); Layout::setupCamera(r); Layout::startDraw(r, eye, 0); s_saving->draw(r, eye, 0); Layout::endDraw(r, 0); nngxFlush3DCommand(); }
