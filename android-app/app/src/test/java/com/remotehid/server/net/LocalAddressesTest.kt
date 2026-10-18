package com.remotehid.server.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalAddressesTest {

    @Test
    fun `usb tether interfaces are recognised under the names Android uses`() {
        for (n in listOf("rndis0", "usb0", "ncm0", "eth0", "eth1")) assertEquals(n, LinkKind.USB, classifyInterface(n))
    }

    @Test
    fun `wifi and hotspot are recognised`() {
        assertEquals(LinkKind.WIFI, classifyInterface("wlan0"))
        assertEquals(LinkKind.HOTSPOT, classifyInterface("ap0"))
        assertEquals(LinkKind.HOTSPOT, classifyInterface("swlan0"))
    }

    @Test
    fun `interfaces that are never a way in are ignored`() {
        for (n in listOf("lo", "rmnet_data1", "ccmni0", "tun0", "dummy0", "v4-rmnet0", "wg0")) assertNull(n, classifyInterface(n))
    }

    @Test
    fun `an unknown interface is kept and shown by name`() {
        assertEquals(LinkKind.OTHER, classifyInterface("bt-pan"))
    }

    private val usb = LocalAddress("rndis0", "192.168.42.129", LinkKind.USB)
    private val wifi = LocalAddress("wlan0", "192.168.100.8", LinkKind.WIFI)

    @Test
    fun `with nothing connected the status says how to get connected`() {
        assertTrue(describeAddresses(emptyList(), 8765).contains("USB tethering"))
    }

    @Test
    fun `one address keeps the familiar one line status`() {
        assertEquals("Listening on ws://192.168.100.8:8765 (Wi-Fi)", describeAddresses(listOf(wifi), 8765))
    }

    @Test
    fun `usb alone is shown even with wifi off, which used to read unknown IP`() {
        assertEquals("Listening on ws://192.168.42.129:8765 (USB cable)", describeAddresses(listOf(usb), 8765))
    }

    @Test
    fun `several addresses are listed one per line`() {
        val text = describeAddresses(listOf(usb, wifi), 8765)
        assertEquals("Listening on:\nUSB cable  ws://192.168.42.129:8765\nWi-Fi  ws://192.168.100.8:8765", text)
    }

    @Test
    fun `an other link is labelled with its interface name`() {
        assertEquals("Listening on ws://10.1.1.2:8765 (bt-pan)", describeAddresses(listOf(LocalAddress("bt-pan", "10.1.1.2", LinkKind.OTHER)), 8765))
    }

    @Test
    fun `collecting works on a real machine without throwing`() {
        val list = collectLocalAddresses()
        assertEquals(list.sortedBy { it.kind.rank }, list)
    }
}
