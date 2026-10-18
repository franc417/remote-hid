package com.remotehid.server.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ProtocolTest {

    @Test
    fun `valid move message passes through unchanged`() {
        val msg = mapOf("t" to "move", "dx" to 5, "dy" to -3)
        assertEquals(msg, parseMessage(msg))
    }

    @Test
    fun `click with no fields defaults to left button and click action`() {
        parseMessage(mapOf("t" to "click")) // should not throw
    }

    @Test
    fun `click down and up for a drag sequence`() {
        parseMessage(mapOf("t" to "click", "action" to "down"))
        parseMessage(mapOf("t" to "click", "action" to "up"))
    }

    @Test
    fun `scroll requires a numeric dy`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("t" to "scroll"))
        }
    }

    @Test
    fun `key with valid modifiers passes`() {
        parseMessage(
            mapOf(
                "t" to "key",
                "code" to "KeyV",
                "action" to "down",
                "mods" to listOf("ctrl"),
            )
        )
    }

    @Test
    fun `key without a mods field defaults to no modifiers`() {
        parseMessage(mapOf("t" to "key", "code" to "Enter", "action" to "down"))
    }

    @Test
    fun `key with invalid modifier is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(
                mapOf(
                    "t" to "key",
                    "code" to "KeyA",
                    "action" to "down",
                    "mods" to listOf("banana"),
                )
            )
        }
    }

    @Test
    fun `key without a code is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("t" to "key", "action" to "down"))
        }
    }

    @Test
    fun `unknown message type is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("t" to "explode"))
        }
    }

    @Test
    fun `move without a numeric dx is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("t" to "move", "dx" to "nope", "dy" to 1))
        }
    }

    @Test
    fun `invalid button is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("t" to "click", "button" to "fourth"))
        }
    }

    @Test
    fun `missing t field is rejected`() {
        assertThrows(ProtocolError::class.java) {
            parseMessage(mapOf("dx" to 1, "dy" to 1))
        }
    }

    @Test
    fun `field message with text and caret passes through unchanged`() {
        val msg = mapOf("t" to "field", "focused" to true, "text" to "cats", "caret" to 2, "password" to false, "name" to "Search")
        assertEquals(msg, parseMessage(msg))
    }

    @Test
    fun `field message that lost focus needs nothing else`() {
        val msg = mapOf("t" to "field", "focused" to false)
        assertEquals(msg, parseMessage(msg))
    }

    @Test
    fun `field message needs a boolean focused`() {
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field")) }
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to "yes")) }
    }

    @Test
    fun `field message rejects wrong types and a negative caret`() {
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to true, "text" to 5)) }
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to true, "name" to 5)) }
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to true, "password" to "x")) }
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to true, "caret" to -1)) }
        assertThrows(ProtocolError::class.java) { parseMessage(mapOf("t" to "field", "focused" to true, "caret" to "2")) }
    }
}
