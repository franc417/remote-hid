package com.remotehid.moonlight

/**
 * Wire-protocol key codes (the same vocabulary [TrackpadView] and [KeyboardView] already
 * emit, and the same one `linux-client/input_backend.py`'s KEY_MAP translates to evdev
 * names) -> Win32 virtual-key codes, which is what moonlight-common-c's LiSendKeyboardEvent
 * expects. Same source vocabulary, different target -- built the same way KEY_MAP was, one
 * entry per key, values checked against Microsoft's own Virtual-Key Codes reference
 * (learn.microsoft.com/windows/win32/inputdev/virtual-key-codes), not guessed.
 *
 * Covers exactly what KEY_MAP covers today: letters, digits, F1-F12, the editing/navigation
 * block, and US-ANSI punctuation. Extend both tables together if the keyboard grows more
 * keys -- a code here with nothing in evdev's KEY_MAP (or vice versa) means the two
 * clients' keyboards have quietly drifted apart.
 */
object VkKeyMap {
    val CODE_TO_VK: Map<String, Int> = buildMap {
        for (letter in 'A'..'Z') put("Key$letter", 0x41 + (letter - 'A'))   // VK_A..VK_Z
        for (digit in '0'..'9') put("Digit$digit", 0x30 + (digit - '0'))    // VK_0..VK_9
        for (n in 1..12) put("F$n", 0x70 - 1 + n)                           // VK_F1 (0x70) .. VK_F12 (0x7B)

        put("Enter", 0x0D)        // VK_RETURN
        put("Backspace", 0x08)    // VK_BACK
        put("Space", 0x20)        // VK_SPACE
        put("Tab", 0x09)          // VK_TAB
        put("Escape", 0x1B)       // VK_ESCAPE
        put("ArrowUp", 0x26)      // VK_UP
        put("ArrowDown", 0x28)    // VK_DOWN
        put("ArrowLeft", 0x25)    // VK_LEFT
        put("ArrowRight", 0x27)   // VK_RIGHT
        put("Home", 0x24)         // VK_HOME
        put("End", 0x23)          // VK_END
        put("PageUp", 0x21)       // VK_PRIOR
        put("PageDown", 0x22)     // VK_NEXT
        put("PrintScreen", 0x2C)  // VK_SNAPSHOT
        put("Meta", 0x5B)         // VK_LWIN

        // US-ANSI OEM punctuation -- "it can vary by keyboard" per Microsoft's own docs, but
        // this is the same US-layout assumption KEY_MAP already makes, so it stays consistent
        // between the two clients rather than introducing a new assumption here.
        put("Semicolon", 0xBA)     // VK_OEM_1
        put("Equal", 0xBB)         // VK_OEM_PLUS
        put("Comma", 0xBC)         // VK_OEM_COMMA
        put("Minus", 0xBD)         // VK_OEM_MINUS
        put("Period", 0xBE)        // VK_OEM_PERIOD
        put("Slash", 0xBF)         // VK_OEM_2
        put("Backquote", 0xC0)     // VK_OEM_3
        put("BracketLeft", 0xDB)   // VK_OEM_4
        put("Backslash", 0xDC)     // VK_OEM_5
        put("BracketRight", 0xDD)  // VK_OEM_6
        put("Quote", 0xDE)         // VK_OEM_7
    }

    /** Left-side modifier VKs -- same left-only choice KEY_MAP/MOD_MAP already makes. */
    val MOD_TO_VK: Map<String, Int> = mapOf(
        "ctrl" to 0xA2,   // VK_LCONTROL
        "alt" to 0xA4,    // VK_LMENU
        "shift" to 0xA0,  // VK_LSHIFT
        "meta" to 0x5B,   // VK_LWIN
    )
}
