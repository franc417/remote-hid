package com.remotehid.server.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

class JsonTest {

    @Test
    fun `encodes a move message`() {
        val json = mapToJson(mapOf("t" to "move", "dx" to 5, "dy" to -3))
        assertEquals("""{"t":"move","dx":5,"dy":-3}""", json)
    }

    @Test
    fun `encodes floats the way MotionEvent coordinates arrive`() {
        val json = mapToJson(mapOf("t" to "move", "dx" to 4.5f, "dy" to -2.0f))
        assertEquals("""{"t":"move","dx":4.5,"dy":-2.0}""", json)
    }

    @Test
    fun `encodes a key message with a mods list`() {
        val json = mapToJson(
            mapOf("t" to "key", "code" to "KeyV", "action" to "down", "mods" to listOf("ctrl"))
        )
        assertEquals("""{"t":"key","code":"KeyV","action":"down","mods":["ctrl"]}""", json)
    }

    @Test
    fun `encodes an empty mods list`() {
        val json = mapToJson(
            mapOf("t" to "key", "code" to "Enter", "action" to "down", "mods" to emptyList<String>())
        )
        assertEquals("""{"t":"key","code":"Enter","action":"down","mods":[]}""", json)
    }

    @Test
    fun `escapes quotes and backslashes in strings`() {
        val json = mapToJson(mapOf("t" to "test", "note" to "say \"hi\" \\ done"))
        assertEquals("""{"t":"test","note":"say \"hi\" \\ done"}""", json)
    }
}
