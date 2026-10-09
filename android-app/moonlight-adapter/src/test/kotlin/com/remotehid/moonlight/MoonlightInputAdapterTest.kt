package com.remotehid.moonlight

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VkKeyMapTest {
    @Test
    fun `letters match Win32 VK_A..VK_Z exactly`() {
        assertEquals(0x41, VkKeyMap.CODE_TO_VK["KeyA"])
        assertEquals(0x5A, VkKeyMap.CODE_TO_VK["KeyZ"])
        assertEquals(0x51, VkKeyMap.CODE_TO_VK["KeyQ"])
    }

    @Test
    fun `digits match Win32 VK_0..VK_9 exactly`() {
        assertEquals(0x30, VkKeyMap.CODE_TO_VK["Digit0"])
        assertEquals(0x39, VkKeyMap.CODE_TO_VK["Digit9"])
    }

    @Test
    fun `function keys are sequential from VK_F1`() {
        assertEquals(0x70, VkKeyMap.CODE_TO_VK["F1"])
        assertEquals(0x7B, VkKeyMap.CODE_TO_VK["F12"])
    }

    @Test
    fun `editing and navigation keys match Limelight's documented Win32 VK values`() {
        assertEquals(0x0D, VkKeyMap.CODE_TO_VK["Enter"])
        assertEquals(0x08, VkKeyMap.CODE_TO_VK["Backspace"])
        assertEquals(0x1B, VkKeyMap.CODE_TO_VK["Escape"])
        assertEquals(0x25, VkKeyMap.CODE_TO_VK["ArrowLeft"])
        assertEquals(0x26, VkKeyMap.CODE_TO_VK["ArrowUp"])
        assertEquals(0x27, VkKeyMap.CODE_TO_VK["ArrowRight"])
        assertEquals(0x28, VkKeyMap.CODE_TO_VK["ArrowDown"])
        assertEquals(0x5B, VkKeyMap.CODE_TO_VK["Meta"])
    }

    @Test
    fun `OEM punctuation matches Microsoft's VK_OEM_ table`() {
        assertEquals(0xBA, VkKeyMap.CODE_TO_VK["Semicolon"])
        assertEquals(0xBB, VkKeyMap.CODE_TO_VK["Equal"])
        assertEquals(0xBC, VkKeyMap.CODE_TO_VK["Comma"])
        assertEquals(0xBD, VkKeyMap.CODE_TO_VK["Minus"])
        assertEquals(0xBE, VkKeyMap.CODE_TO_VK["Period"])
        assertEquals(0xBF, VkKeyMap.CODE_TO_VK["Slash"])
        assertEquals(0xC0, VkKeyMap.CODE_TO_VK["Backquote"])
        assertEquals(0xDB, VkKeyMap.CODE_TO_VK["BracketLeft"])
        assertEquals(0xDC, VkKeyMap.CODE_TO_VK["Backslash"])
        assertEquals(0xDD, VkKeyMap.CODE_TO_VK["BracketRight"])
        assertEquals(0xDE, VkKeyMap.CODE_TO_VK["Quote"])
    }

    @Test
    fun `every code the Linux client's KEY_MAP covers also has a VK entry`() {
        val lettersAndDigits = ('A'..'Z').map { "Key$it" } + ('0'..'9').map { "Digit$it" }
        val fKeys = (1..12).map { "F$it" }
        val named = listOf(
            "Enter", "Backspace", "Space", "Tab", "Escape",
            "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
            "Comma", "Period", "Minus", "Equal", "PrintScreen",
            "Home", "End", "PageUp", "PageDown", "Meta",
            "Semicolon", "Quote", "Slash", "Backslash",
            "BracketLeft", "BracketRight", "Backquote",
        )
        for (code in lettersAndDigits + fKeys + named) {
            assertTrue("missing VK mapping for '$code'", VkKeyMap.CODE_TO_VK.containsKey(code))
        }
    }

    @Test
    fun `modifier map is left-side only, matching MOD_MAP on the Linux side`() {
        assertEquals(4, VkKeyMap.MOD_TO_VK.size)
        assertEquals(0xA0, VkKeyMap.MOD_TO_VK["shift"])
        assertEquals(0xA2, VkKeyMap.MOD_TO_VK["ctrl"])
        assertEquals(0xA4, VkKeyMap.MOD_TO_VK["alt"])
        assertEquals(0x5B, VkKeyMap.MOD_TO_VK["meta"])
    }
}

class MoonlightInputAdapterTest {
    @Test
    fun `move translates dx dy straight through`() {
        val cmd = MoonlightInputAdapter.translate(mapOf("t" to "move", "dx" to 5, "dy" to -3))
        assertEquals(MoonlightCommand.MouseMove(5, -3), cmd)
    }

    @Test
    fun `move clamps out-of-range values to short bounds rather than overflowing`() {
        val cmd = MoonlightInputAdapter.translate(mapOf("t" to "move", "dx" to 999999, "dy" to -999999))
        assertEquals(MoonlightCommand.MouseMove(Short.MAX_VALUE, Short.MIN_VALUE), cmd)
    }

    @Test
    fun `explicit click down then up produce the documented action bytes`() {
        val down = MoonlightInputAdapter.translate(mapOf("t" to "click", "button" to "left", "action" to "down"))
        val up = MoonlightInputAdapter.translate(mapOf("t" to "click", "button" to "left", "action" to "up"))
        assertEquals(MoonlightCommand.MouseButton(1, MoonlightInputAdapter.BUTTON_ACTION_PRESS), down)
        assertEquals(MoonlightCommand.MouseButton(1, MoonlightInputAdapter.BUTTON_ACTION_RELEASE), up)
    }

    @Test
    fun `bare click with no action expands to press then release, matching UinputBackend`() {
        val cmds = MoonlightInputAdapter.translateClick(mapOf("t" to "click", "button" to "right"))
        assertEquals(
            listOf(
                MoonlightCommand.MouseButton(3, MoonlightInputAdapter.BUTTON_ACTION_PRESS),
                MoonlightCommand.MouseButton(3, MoonlightInputAdapter.BUTTON_ACTION_RELEASE),
            ),
            cmds,
        )
    }

    @Test
    fun `scroll uses the high-res short path, not the coarse click-count one`() {
        val cmd = MoonlightInputAdapter.translate(mapOf("t" to "scroll", "dy" to 7))
        assertEquals(MoonlightCommand.Scroll(7), cmd)
    }

    @Test
    fun `key down carries the modifier bitmask instead of separate modifier keypresses`() {
        val cmd = MoonlightInputAdapter.translate(
            mapOf("t" to "key", "code" to "KeyA", "action" to "down", "mods" to listOf("shift", "ctrl"))
        )
        assertEquals(
            MoonlightCommand.Key(0x41, MoonlightInputAdapter.KEY_ACTION_DOWN, (0x01 or 0x02).toByte()),
            cmd,
        )
    }

    @Test
    fun `key with no mods gets a zero modifier byte, not null or a crash`() {
        val cmd = MoonlightInputAdapter.translate(mapOf("t" to "key", "code" to "Enter", "action" to "up"))
        assertEquals(MoonlightCommand.Key(0x0D, MoonlightInputAdapter.KEY_ACTION_UP, 0), cmd)
    }

    @Test
    fun `unrecognized key code is skipped, not crashed on`() {
        val cmd = MoonlightInputAdapter.translate(mapOf("t" to "key", "code" to "SomeFutureKey", "action" to "down"))
        assertEquals(MoonlightCommand.Unknown, cmd)
    }

    @Test
    fun `unrecognized event type is skipped`() {
        assertEquals(MoonlightCommand.Unknown, MoonlightInputAdapter.translate(mapOf("t" to "wave")))
    }

    @Test
    fun `missing required field is skipped rather than throwing`() {
        assertEquals(MoonlightCommand.Unknown, MoonlightInputAdapter.translate(mapOf("t" to "move", "dx" to 5)))
    }
}
