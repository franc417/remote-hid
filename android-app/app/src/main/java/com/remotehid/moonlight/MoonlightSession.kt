package com.remotehid.moonlight

import com.remotehid.server.input.KeyboardView
import com.remotehid.server.input.TrackpadView

/**
 * UNVERIFIED -- cannot be compiled or exercised outside a real Android build with moonlight-
 * common-c's native library actually linked in. There is no Android SDK/NDK and no compiled
 * .so in the sandbox this was written in. Everything above the `external fun` boundary
 * (MoonlightInputAdapter, VkKeyMap, in the sibling :moonlight-adapter module) is plain Kotlin
 * and genuinely unit-tested; this file is the thin, necessarily-native-dependent layer on
 * top of it, and needs real on-device testing before being trusted.
 *
 * The four functions below are declared with moonlight-common-c's actual signatures (from
 * Limelight.h), not guessed. What's NOT here: the JNI bridge .c/.cpp implementing them by
 * calling the real C LiSendMouseMoveEvent etc, and the CMake/NDK build wiring that produces
 * the .so this class's System.loadLibrary() call expects. moonlight-android's own repo
 * already has a working version of that bridge (same GPL-3.0 as moonlight-common-c itself,
 * already accepted for this project) -- adapting theirs is almost certainly less work and
 * less risk than writing a new one from scratch, and is the natural next step here.
 */
internal object MoonlightNative {
    init {
        System.loadLibrary("moonlight-core") // placeholder name -- matches whatever the real NDK build target ends up being called
    }

    // Limelight.h: int LiSendMouseMoveEvent(short deltaX, short deltaY);
    external fun sendMouseMove(deltaX: Short, deltaY: Short): Int

    // Limelight.h: int LiSendMouseButtonEvent(char action, int button);
    external fun sendMouseButton(action: Byte, button: Int): Int

    // Limelight.h: int LiSendHighResScrollEvent(short scrollAmount);
    external fun sendHighResScroll(scrollAmount: Short): Int

    // Limelight.h: int LiSendKeyboardEvent(short keyCode, char keyAction, char modifiers);
    external fun sendKeyboardEvent(keyCode: Short, keyAction: Byte, modifiers: Byte): Int
}

/**
 * Dispatches one already-translated [MoonlightCommand] to the matching native call. Kept
 * separate from [MoonlightInputAdapter] on purpose: that object is pure translation logic
 * and has real tests; this `when` is a one-line-per-case mechanical mapping with nothing
 * left to get wrong once the translation itself is correct, so it doesn't need its own
 * parallel test suite -- it needs a real device to prove the JNI/native side actually works.
 */
internal fun dispatch(command: MoonlightCommand) {
    when (command) {
        is MoonlightCommand.MouseMove -> MoonlightNative.sendMouseMove(command.dx, command.dy)
        is MoonlightCommand.MouseButton -> MoonlightNative.sendMouseButton(command.action, command.button)
        is MoonlightCommand.Scroll -> MoonlightNative.sendHighResScroll(command.amount)
        is MoonlightCommand.Key -> MoonlightNative.sendKeyboardEvent(command.vkCode, command.action, command.modifiers)
        is MoonlightCommand.Unknown -> Unit // nothing to send -- MoonlightInputAdapter already decided to skip this
    }
}

/**
 * Wires [TrackpadView] and [KeyboardView]'s onEvent callbacks to the Moonlight session
 * instead of remote-hid's own WebSocket transport. This is the entire integration point --
 * compare to MainActivity.kt's own two-line wiring to `service?.sendToClient(...)`, which
 * this replaces for Mesh's use rather than remote-hid's HID-server use. Call once after
 * both views are created, same as MainActivity already does for its own wiring.
 */
fun wireMoonlightInput(trackpad: TrackpadView, keyboard: KeyboardView) {
    // translateClick, not translate: TrackpadView emits a bare {"t":"click","button":"left"}
    // (no "action") for a plain tap -- plain translate() defaults a missing action to "down"
    // only, which would press and never release. translateClick() is the one that expands
    // that bare case to [press, release]; it passes explicit down/up events through
    // unchanged, so it's correct for every click shape TrackpadView actually emits, not just
    // the bare one.
    trackpad.onEvent = { event -> MoonlightInputAdapter.translateClick(event).forEach(::dispatch) }
    keyboard.onEvent = { event -> dispatch(MoonlightInputAdapter.translate(event)) }
}
