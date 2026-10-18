package com.remotehid.server.input

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TypingModelTest {

    private fun field(text: String, caret: Int, name: String = "", password: Boolean = false) =
        mapOf("t" to "field", "focused" to true, "text" to text, "caret" to caret, "name" to name, "password" to password)

    @Test
    fun `without a desktop report the bar is the local echo`() {
        val m = TypingModel()
        assertFalse(m.shown().visible)
        m.onLocalEcho("hel")
        assertEquals(TypingShown(true, before = "hel"), m.shown())
        m.onLocalEcho("")
        assertFalse(m.shown().visible)
    }

    @Test
    fun `a desktop report shows the real text with the caret where the desktop says`() {
        val m = TypingModel()
        m.onFieldMessage(field("hello world", 5, "Search"))
        assertEquals(TypingShown(true, "Search", "hello", " world", true), m.shown())
    }

    @Test
    fun `the real field beats the local echo`() {
        val m = TypingModel()
        m.onLocalEcho("typed on the phone")
        m.onFieldMessage(field("what is really there", 4))
        assertEquals("what", m.shown().before)
    }

    @Test
    fun `deleting text on the desktop is reflected, which a local echo cannot know`() {
        val m = TypingModel()
        m.onFieldMessage(field("abc", 3))
        m.onFieldMessage(field("ab", 2))
        assertEquals("ab", m.shown().before)
    }

    @Test
    fun `no focused text field hides the bar even if the phone typed something`() {
        val m = TypingModel()
        m.onLocalEcho("stale")
        m.onFieldMessage(mapOf("t" to "field", "focused" to false))
        assertFalse(m.shown().visible)
    }

    @Test
    fun `a focused empty field shows just the caret and its name`() {
        val m = TypingModel()
        m.onFieldMessage(field("", 0, "Address bar"))
        assertEquals(TypingShown(true, "Address bar", "", "", true), m.shown())
    }

    @Test
    fun `an unnamed field is captioned Typing`() {
        val m = TypingModel()
        m.onFieldMessage(field("x", 1))
        assertEquals("Typing", m.shown().label)
    }

    @Test
    fun `a password is shown as bullets even if the sender sent real text`() {
        val m = TypingModel()
        m.onFieldMessage(field("hunter2", 7, "Password", password = true))
        val s = m.shown()
        assertEquals("\u2022".repeat(7), s.before)
        assertFalse((s.before + s.after).contains("hunter2"))
    }

    @Test
    fun `an out of range caret is clamped`() {
        val m = TypingModel()
        m.onFieldMessage(field("abc", 99))
        assertEquals(TypingShown(true, "Typing", "abc", "", true), m.shown())
    }

    @Test
    fun `a missing caret puts it at the end`() {
        val m = TypingModel()
        m.onFieldMessage(mapOf("t" to "field", "focused" to true, "text" to "abc"))
        assertEquals("abc", m.shown().before)
    }

    @Test
    fun `newlines are flattened so the bar stays one line`() {
        val m = TypingModel()
        m.onFieldMessage(field("a\nb", 1))
        assertFalse((m.shown().before + m.shown().after).contains("\n"))
    }

    @Test
    fun `disconnecting forgets the old field and falls back to the local echo`() {
        val m = TypingModel()
        m.onFieldMessage(field("secret draft", 3))
        m.onDisconnected()
        assertFalse(m.shown().visible)
        m.onLocalEcho("new")
        assertEquals(TypingShown(true, before = "new"), m.shown())
    }
}
