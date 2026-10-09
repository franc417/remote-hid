package com.remotehid.moonlight

/**
 * What [MoonlightInputAdapter] decided to do with one incoming event, as data rather than a
 * direct JNI call -- so the translation logic (the part most likely to have a bug) is plain,
 * testable Kotlin with no Android or native dependency, the same reasoning remote-hid's own
 * Protocol.kt already uses. The Android-side wrapper (not in this module, since it needs the
 * real native library) pattern-matches on these and calls the matching Li* function.
 *
 * Field names and values are deliberately the exact parameter shapes LiSend*Event() takes
 * (see moonlight-common-c/src/Limelight.h), not a generic down/up boolean -- e.g. mouse and
 * keyboard actions are specific byte codes (0x07/0x08, 0x03/0x04), not 0/1, and getting that
 * wrong would be exactly the kind of bug this split is meant to let a unit test catch.
 */
sealed class MoonlightCommand {
    data class MouseMove(val dx: Short, val dy: Short) : MoonlightCommand()
    data class MouseButton(val button: Int, val action: Byte) : MoonlightCommand()
    data class Scroll(val amount: Short) : MoonlightCommand()
    data class Key(val vkCode: Short, val action: Byte, val modifiers: Byte) : MoonlightCommand()

    /** Event shape or key/button code we don't recognize. Skip it, don't crash the session --
     * same "unknown key -> skip rather than crash the connection" choice UinputBackend.key()
     * already makes on the Linux side. */
    object Unknown : MoonlightCommand()
}

object MoonlightInputAdapter {
    // Limelight.h: LiSendMouseButtonEvent(char action, int button)
    const val BUTTON_ACTION_PRESS: Byte = 0x07
    const val BUTTON_ACTION_RELEASE: Byte = 0x08
    private const val BUTTON_LEFT = 0x01
    private const val BUTTON_MIDDLE = 0x02
    private const val BUTTON_RIGHT = 0x03

    // Limelight.h: LiSendKeyboardEvent(short keyCode, char keyAction, char modifiers)
    const val KEY_ACTION_DOWN: Byte = 0x03
    const val KEY_ACTION_UP: Byte = 0x04
    private const val MODIFIER_SHIFT = 0x01
    private const val MODIFIER_CTRL = 0x02
    private const val MODIFIER_ALT = 0x04
    private const val MODIFIER_META = 0x08

    /** [TrackpadView]/[KeyboardView]'s event shape in, a [MoonlightCommand] out. One event
     * in, one command out -- unlike the Linux backend, which has to synthesize separate
     * modifier keypresses itself (raw evdev has no concept of "this key, with these
     * modifiers"), moonlight-common-c's protocol carries the modifier state as a bitmask
     * alongside the single key event, so there's nothing to expand here. */
    fun translate(event: Map<String, Any?>): MoonlightCommand = when (event["t"] as? String) {
        "move" -> {
            val dx = (event["dx"] as? Number)?.toInt()
            val dy = (event["dy"] as? Number)?.toInt()
            if (dx == null || dy == null) MoonlightCommand.Unknown
            else MoonlightCommand.MouseMove(clampToShort(dx), clampToShort(dy))
        }
        "click" -> {
            val button = buttonCode(event["button"] as? String)
            val action = actionByte(event["action"] as? String ?: "down")
            if (button == null || action == null) MoonlightCommand.Unknown
            else MoonlightCommand.MouseButton(button, action)
        }
        "scroll" -> {
            val dy = (event["dy"] as? Number)?.toInt()
            if (dy == null) MoonlightCommand.Unknown else MoonlightCommand.Scroll(clampToShort(dy))
        }
        "key" -> {
            val vk = VkKeyMap.CODE_TO_VK[event["code"] as? String]
            val action = when (event["action"] as? String) {
                "down" -> KEY_ACTION_DOWN
                "up" -> KEY_ACTION_UP
                else -> null
            }
            if (vk == null || action == null) MoonlightCommand.Unknown
            else MoonlightCommand.Key(vk.toShort(), action, modifierMask(event["mods"]))
        }
        else -> MoonlightCommand.Unknown
    }

    /** TrackpadView's bare "click" (no explicit action) means press-then-release as one
     * logical click -- expand it the same way UinputBackend.click() does on the Linux side
     * (both writes when action=="click"), rather than picking just one here. Everything else
     * `translate()` returns is already exactly one command; only this needs expanding to two. */
    fun translateClick(event: Map<String, Any?>): List<MoonlightCommand> {
        if (event["t"] as? String != "click" || event["action"] != null) {
            return listOf(translate(event))
        }
        val button = buttonCode(event["button"] as? String) ?: return listOf(MoonlightCommand.Unknown)
        return listOf(
            MoonlightCommand.MouseButton(button, BUTTON_ACTION_PRESS),
            MoonlightCommand.MouseButton(button, BUTTON_ACTION_RELEASE),
        )
    }

    private fun buttonCode(button: String?): Int? = when (button) {
        "left" -> BUTTON_LEFT
        "middle" -> BUTTON_MIDDLE
        "right" -> BUTTON_RIGHT
        else -> null
    }

    private fun actionByte(action: String?): Byte? = when (action) {
        "down" -> BUTTON_ACTION_PRESS
        "up" -> BUTTON_ACTION_RELEASE
        else -> null
    }

    private fun modifierMask(mods: Any?): Byte {
        val list = mods as? List<*> ?: return 0
        var mask = 0
        if ("shift" in list) mask = mask or MODIFIER_SHIFT
        if ("ctrl" in list) mask = mask or MODIFIER_CTRL
        if ("alt" in list) mask = mask or MODIFIER_ALT
        if ("meta" in list) mask = mask or MODIFIER_META
        return mask.toByte()
    }

    private fun clampToShort(v: Int): Short = v.coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
}
