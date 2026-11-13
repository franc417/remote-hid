package com.remotehid.server.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TetherTest {

    private val wifi = LocalAddress("wlan0", "192.168.0.101", LinkKind.WIFI)
    private val usb = LocalAddress("rndis0", "192.168.42.129", LinkKind.USB)
    private val ap = LocalAddress("ap0", "192.168.43.1", LinkKind.HOTSPOT)

    private fun signals(connected: Boolean? = null, rndis: Boolean? = null, plugged: Boolean = false, addresses: List<LocalAddress> = emptyList()) =
        TetherSignals(connected, rndis, plugged, addresses)

    @Test
    fun `nothing plugged and nothing tethering is hidden`() {
        val status = computeTetherStatus(signals(connected = false, addresses = listOf(wifi)))
        assertFalse(status.cableConnected)
        assertFalse(status.tethering)
        assertEquals(TetherMode.HIDDEN, tetherView(status, false).mode)
    }

    @Test
    fun `a cable in with tethering off prompts to turn it on`() {
        val view = tetherView(computeTetherStatus(signals(connected = true, rndis = false, addresses = listOf(wifi))), false)
        assertEquals(TetherMode.PROMPT, view.mode)
        assertEquals("Turn on tethering", view.buttonText)
        assertTrue(view.detail.contains("USB tethering"))
    }

    @Test
    fun `usb tethering on becomes the small circle and shows the cable address in the panel`() {
        val status = computeTetherStatus(signals(connected = true, rndis = true, addresses = listOf(usb)))
        assertTrue(status.usbTether)
        assertEquals("192.168.42.129", status.usbAddress)
        val circle = tetherView(status, false)
        assertEquals(TetherMode.CIRCLE, circle.mode)
        assertEquals("T", circle.title)
        val panel = tetherView(status, true)
        assertEquals(TetherMode.PANEL, panel.mode)
        assertTrue(panel.detail.contains("USB tethering: on · 192.168.42.129"))
        assertTrue(panel.detail.contains("Wi-Fi hotspot: off"))
        assertTrue(panel.detail.contains("tap here to shrink"))
    }

    @Test
    fun `tapping the circle and the panel header toggles between the two`() {
        val status = computeTetherStatus(signals(connected = true, rndis = true, addresses = listOf(usb)))
        assertEquals(TetherMode.CIRCLE, tetherView(status, expanded = false).mode)
        assertEquals(TetherMode.PANEL, tetherView(status, expanded = true).mode)
        assertEquals(TetherMode.CIRCLE, tetherView(status, expanded = false).mode)
    }

    @Test
    fun `the function being on counts even before the cable has an address`() {
        val status = computeTetherStatus(signals(connected = true, rndis = true))
        assertTrue(status.usbTether)
        assertEquals(null, status.usbAddress)
        assertTrue(tetherView(status, true).detail.contains("USB tethering: on"))
    }

    @Test
    fun `an address on a cable interface counts as tethering even when the system says nothing about it`() {
        assertTrue(computeTetherStatus(signals(addresses = listOf(usb))).usbTether)
    }

    @Test
    fun `a hotspot is recognised by its interface`() {
        val status = computeTetherStatus(signals(addresses = listOf(ap)))
        assertTrue(status.hotspot)
        assertEquals("192.168.43.1", status.hotspotAddress)
        assertTrue(tetherView(status, true).detail.contains("Wi-Fi hotspot: on · 192.168.43.1"))
        assertEquals(TetherMode.CIRCLE, tetherView(status, false).mode)
    }

    @Test
    fun `a second wifi interface that is the router counts as a hotspot but the phones own wifi does not`() {
        assertTrue(isHotspotAddress(LocalAddress("wlan1", "192.168.43.1", LinkKind.WIFI)))
        assertFalse(isHotspotAddress(LocalAddress("wlan1", "192.168.43.77", LinkKind.WIFI)))
        assertFalse(isHotspotAddress(LocalAddress("wlan0", "192.168.0.1", LinkKind.WIFI)))
        assertFalse(isHotspotAddress(wifi))
    }

    @Test
    fun `without the usb state the battery plug stands in for the cable`() {
        assertTrue(computeTetherStatus(signals(connected = null, plugged = true)).cableConnected)
        assertFalse(computeTetherStatus(signals(connected = null, plugged = false)).cableConnected)
    }

    @Test
    fun `a charger that is not talking to a computer does not raise the prompt when the system says so`() {
        val status = computeTetherStatus(signals(connected = false, plugged = true))
        assertFalse(status.cableConnected)
        assertEquals(TetherMode.HIDDEN, tetherView(status, false).mode)
    }

    @Test
    fun `both tethers on are listed together`() {
        val view = tetherView(computeTetherStatus(signals(connected = true, rndis = true, addresses = listOf(usb, ap))), true)
        assertTrue(view.detail.contains("USB tethering: on"))
        assertTrue(view.detail.contains("Wi-Fi hotspot: on"))
    }
}
