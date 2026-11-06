package com.remotehid.server.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetAddress

class RendezvousTest {

    @Test
    fun `one address keeps the format the app always understood`() {
        assertEquals(Rendezvous(listOf("192.168.1.5"), 8766), parseRendezvous("192.168.1.5:8766"))
    }

    @Test
    fun `several addresses are tried in the order the desktop listed them`() {
        assertEquals(Rendezvous(listOf("192.168.1.5", "192.168.43.17"), 8766), parseRendezvous("192.168.1.5,192.168.43.17:8766"))
    }

    @Test
    fun `spaces and a trailing newline do not matter`() {
        assertEquals(Rendezvous(listOf("10.0.0.2", "10.0.1.2"), 9000), parseRendezvous("  10.0.0.2 , 10.0.1.2 :9000\n"))
    }

    @Test
    fun `text that is not an address list is refused`() {
        for (bad in listOf("", "hello", ":8766", "192.168.1.5", "192.168.1.5:", "192.168.1.5:abc", "192.168.1.5:0", "192.168.1.5:70000", ",:8766")) {
            assertNull(bad, parseRendezvous(bad))
        }
    }

    @Test
    fun `home hotspot and cable addresses are local but public ones are not`() {
        for (local in listOf("192.168.43.17", "10.42.0.1", "172.20.10.2", "169.254.3.4")) {
            assertTrue(local, isLocalTarget(InetAddress.getByName(local)))
        }
        for (other in listOf("8.8.8.8", "100.67.163.21", "93.184.216.34")) {
            assertFalse(other, isLocalTarget(InetAddress.getByName(other)))
        }
    }
}
