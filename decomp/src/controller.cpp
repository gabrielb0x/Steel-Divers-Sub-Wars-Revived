// source/controller.cpp (controller.o): the inputs, read once per frame: buttons, Circle Pad, touch screen,
// accelerometer, gyroscope, the Circle Pad Pro (nn::hid ExtraPad), and the developers' debug pad.
//
// Reconstructed by hand from decomp/raw/source/controller.cpp and the disassembly. Not compilable on its own.
// The scripts read it through the natives sysGetButtons*, sysGetStick... (amxsys.cpp).

struct ButtonSet {                      // 0x14 bytes
	u32 clicked;                        // pressed this frame
	u32 down;
	u32 released;
	u32 repeated;                       // after 16 frames held, every third frame: `down`
	u32 held;                           // frames held
};

class Controller {
	ButtonSet sets[3];                  // +0x00 0: the console's buttons (or the Circle Pad Pro's),
	                                    //       1: the debug pad translated to 3DS buttons, 2: the debug pad raw
	s32 touchX, touchY;                 // +0x3C
	s32 stickX, stickY;                 // +0x44 Circle Pad (-145..145, more with the Circle Pad Pro)
	s32 extraStickX, extraStickY;       // +0x4C the right stick (debug pad, Circle Pad Pro)
	bool touching;                      // +0x54
	bool touchReleased;                 // +0x55 the screen was released since reset(): touches count
	bool touchDisabled;                 // +0x56
	int shakeCounter;                   // +0x58
	bool shaken;                        // +0x5C one frame
};

static nn::hid::PadReader *s_pad;                 // 0x0038E978
static nn::hid::DebugPadReader *s_debugPad;       // 0x0038E97C
static void *s_extraPadMemory;                    // 0x0038E980 4 KB aligned on 4 KB
static nn::hid::ExtraPadReader *s_extraPad;       // 0x0038E984
static nn::hid::AccelerometerReader *s_accel;     // 0x0038E988
static nn::hid::TouchPanelReader *s_touch;        // 0x0038E98C
static nn::hid::GyroscopeReader *s_gyro;          // 0x0038E974
static bool s_detectRunning;                      // 0x0038E970
static bool s_extraPadWanted;                     // 0x0038E971 enableExtraPad
static nn::os::LightEvent s_detect;               // 0x0038E9A8 wakes the detection thread
static nn::os::Thread s_detectThread;             // 0x0038E9A0 (stack 0x005920A8, priority 0x10)
static nn::hid::PadStatus s_padStatus;            // 0x00591C5C
static nn::hid::DebugPadStatus s_debugStatus;     // 0x00591C6C
static nn::hid::ExtraPadStatus s_extraStatus;     // 0x00591C84 (battery +0x14, connected +0x15)
static nn::hid::AccelerationFloat s_acceleration; // 0x00591C9C
static nn::hid::GyroscopeStatus s_gyroStatus;     // 0x00591C20 (angle at +0x0C)

// 0x00107BE4: the readers, the gyroscope's zero-drift setting, and the thread that looks for a Circle Pad
// Pro. A thread that cannot start is a fatal error (nn::err::ThrowFatalErrAll).
void Controller::init();

// 0x001013C0: a new screen: touches count only after the screen has been released.
void Controller::reset() { touchReleased = touching = shaken = false; }

// 0x00110A80 (thread): when woken and no Circle Pad Pro is connected, starts its sampling (8 ms); on
// failure, sleeps a second.
static void DetectExtraPadThreadFunc();

// 0x0017623C / 0x001762AC: the scripts' sysExtraPadStartSampling / StopSampling (the controls screen).
void Controller::enableExtraPad();
void Controller::disableExtraPad();

// The debug pad's buttons as the console's (set 1).
static const struct { u32 debug, ctr; } kDebugToCtr[] = {
	{0x0001, 0x0040}, {0x0002, 0x0020}, {0x0004, 0x8000}, {0x0008, 0x0400}, {0x0010, 0x0001},
	{0x0020, 0x0800}, {0x0040, 0x0002}, {0x0080, 0x4000}, {0x0200, 0x0100}, {0x0400, 0x0008},
	{0x2000, 0x0200}, {0x4000, 0x0080}, {0x8000, 0x0010},
};

// 0x00107E54, every frame.
void Controller::read()
{
	if (nn::hid::ExtraPad::GetConnectionState() == 2)               // lost
		nn::hid::ExtraPad::StopSampling();
	// (the detection thread is woken while a Circle Pad Pro is wanted and not connected)
	u32 buttons[3] = {};
	bool extra = nn::hid::ExtraPad::IsSampling();
	if (extra) {
		s_extraPad->ReadLatest(&s_extraStatus);
		buttons[0] = s_extraStatus.hold;
	} else {
		s_extraStatus.connected = false;
		s_pad->ReadLatest(&s_padStatus);
		s_debugPad->ReadLatest(&s_debugStatus);
		buttons[0] = s_padStatus.hold;
		buttons[2] = s_debugStatus.hold;
		for (auto m : kDebugToCtr)
			if (s_debugStatus.hold & m.debug)
				buttons[1] |= m.ctr;
	}
	s_accel->ReadLatest(&s_accelRaw);
	s_accel->ConvertToAcceleration(&s_acceleration, 1, &s_accelRaw);

	// A sideways shake: |x| above 0.4 g starts a count; |x| back under 0.1 g within 4 frames gives
	// `shaken` for a frame; then 5 frames of rest. (The test on y compares the floats' bits as integers
	// with -0.9's: it passes for y >= 0 or y < -0.9.)
	shaken = false;
	if (shakeCounter > 0) {
		if (++shakeCounter > 4)
			shakeCounter = -1;
		if (fabsf(s_acceleration.x) < 0.1f) {
			shaken = true;
			shakeCounter = -1;
		}
	} else if (shakeCounter < 0) {
		if (--shakeCounter < -5)
			shakeCounter = 0;
	} else if (fabsf(s_acceleration.x) > 0.4f && bitsAsInt(s_acceleration.y) > bitsAsInt(-0.9f)) {
		shakeCounter = 1;
	}

	if (!touchDisabled) {
		nn::hid::TouchPanelStatus t;
		s_touch->ReadLatest(&t);
		if (!t.touch)
			touchReleased = true;
		if (touchReleased) {
			touching = t.touch;
			touchX = t.x;
			touchY = t.y;
		}
	}
	if (extra) {
		stickX = s_extraStatus.stick.x;
		stickY = s_extraStatus.stick.y;
		extraStickX = s_extraStatus.extraStick.x;
		extraStickY = s_extraStatus.extraStick.y;
	} else {                            // the debug pad's sticks (-1..1) merged into the Circle Pad's
		stickX = (s16)((int)(s_debugStatus.leftStickX * 145.0f) | s_padStatus.stick.x);
		stickY = (s16)((int)(s_debugStatus.leftStickY * 145.0f) | s_padStatus.stick.y);
		extraStickX = (s16)(s_debugStatus.rightStickX * 145.0f);
		extraStickY = (s16)(s_debugStatus.rightStickY * 145.0f);
	}
	s_gyro->ReadLatest(&s_gyroStatus);
	for (int i = 0; i < 3; i++) {
		ButtonSet &s = sets[i];
		s.clicked = buttons[i] & ~s.down;
		s.released = s.down & ~buttons[i];
		s.down = buttons[i];
		s.repeated = 0;
		if (buttons[i] == 0)
			s.held = 0;
		else if (++s.held > 15 && s.held % 3 == 0)
			s.repeated = s.down;
	}
}

// The gyroscope (0x00176200, 0x00176280, 0x00176314): its angles (turns) in radians, the bearing
// (atan2f) and the elevation (asinf) of its direction; the accelerometer (0x001762EC).
bool Controller::getGyroAngle(VEC3 *out)
{
	out->x = s_gyroStatus.angle.x * 6.2831855f;
	out->y = s_gyroStatus.angle.y * 6.2831855f;
	out->z = s_gyroStatus.angle.z * 6.2831855f;
	return true;
}
bool Controller::getAcceleration(VEC3 *out) { *out = s_acceleration; return true; }
bool Controller::checkExtraPadBattery() { return s_extraStatus.batteryLow == 1; }      // 0x00176350
bool Controller::checkExtraPadConnected() { return s_extraStatus.connected; }          // 0x00176394
