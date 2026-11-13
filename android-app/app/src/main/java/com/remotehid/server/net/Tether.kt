package com.remotehid.server.net

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.provider.Settings

/** What the phone can tell about its cable and tethering right now. Null = the system did not say. */
data class TetherSignals(
    val usbDataConnected: Boolean?,   // the USB_STATE broadcast's "connected": plugged in to something that talks data (a computer)
    val rndis: Boolean?,              // its "rndis": the USB tethering function is switched on
    val pluggedUsb: Boolean,          // the battery's plugged state is USB (fallback when USB_STATE says nothing)
    val addresses: List<LocalAddress>,
)

data class TetherStatus(
    val cableConnected: Boolean,
    val usbTether: Boolean,
    val usbAddress: String?,
    val hotspot: Boolean,
    val hotspotAddress: String?,
) {
    val tethering: Boolean get() = usbTether || hotspot
}

/**
 * A hotspot shows up as ap0 / swlan0, or as a second Wi-Fi interface (wlan1...) whose address ends in .1 because the phone is
 * the router. This is a guess from the interface, which is all an app can see: reading the hotspot switch itself is not allowed.
 */
fun isHotspotAddress(address: LocalAddress): Boolean =
    address.kind == LinkKind.HOTSPOT || (Regex("wlan[1-9]\\d*").matches(address.ifName.lowercase()) && address.ip.endsWith(".1"))

fun computeTetherStatus(signals: TetherSignals): TetherStatus {
    val usb = signals.addresses.firstOrNull { it.kind == LinkKind.USB }
    val hotspot = signals.addresses.firstOrNull { isHotspotAddress(it) }
    val usbTether = signals.rndis == true || usb != null
    val cable = signals.usbDataConnected ?: signals.pluggedUsb
    return TetherStatus(cable || usbTether, usbTether, usb?.ip, hotspot != null, hotspot?.ip)
}

enum class TetherMode { HIDDEN, PROMPT, CIRCLE, PANEL }

data class TetherView(val mode: TetherMode, val title: String, val detail: String, val buttonText: String)

/**
 * What the tether control shows:
 *  - nothing, while there is no cable and nothing is tethering;
 *  - a prompt with a button, when the cable is in but tethering is off (the button opens the system tethering page: an app cannot
 *    switch tethering on itself, Android keeps that for the system);
 *  - once tethering is on, a small green "T" circle;
 *  - tapping the circle opens a panel with the status; tapping the panel's header goes back to the circle.
 */
fun tetherView(status: TetherStatus, expanded: Boolean): TetherView {
    val details = ArrayList<String>()
    details.add("USB tethering: " + if (status.usbTether) "on" + (status.usbAddress?.let { " · $it" } ?: "") else "off")
    details.add("Wi-Fi hotspot: " + if (status.hotspot) "on" + (status.hotspotAddress?.let { " · $it" } ?: "") else "off")
    return when {
        status.tethering && !expanded -> TetherView(TetherMode.CIRCLE, "T", details.joinToString("\n"), "")
        status.tethering -> TetherView(TetherMode.PANEL, "Tethering is on", details.joinToString("\n") + "\n(tap here to shrink)", "Tethering settings")
        status.cableConnected -> TetherView(
            TetherMode.PROMPT,
            "Cable connected",
            "Turn on USB tethering so the computer can find this phone by itself.",
            "Turn on tethering",
        )
        else -> TetherView(TetherMode.HIDDEN, "", "", "")
    }
}

/** Reads the cable and tether signals. Every read is best effort: a phone that says nothing just reads as "no cable". */
fun readTetherSignals(context: Context): TetherSignals {
    var connected: Boolean? = null
    var rndis: Boolean? = null
    var plugged = false
    try {
        val usb = context.registerReceiver(null, IntentFilter("android.hardware.usb.action.USB_STATE"))
        val extras = usb?.extras
        if (extras != null) {
            if (extras.containsKey("connected")) connected = extras.getBoolean("connected")
            if (extras.containsKey("rndis")) rndis = extras.getBoolean("rndis")
        }
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) == BatteryManager.BATTERY_PLUGGED_USB
    } catch (e: Exception) {
        // keep whatever was read
    }
    return TetherSignals(connected, rndis, plugged, collectLocalAddresses())
}

/**
 * Opens the system's tethering page (where the switch is), trying the places it lives on different Android versions and makers,
 * then the general network settings. Returns false when none could be opened.
 */
fun openTetherSettings(context: Context): Boolean {
    val attempts = listOf(
        Intent().setClassName("com.android.settings", "com.android.settings.TetherSettings"),
        Intent().setClassName("com.android.settings", "com.android.settings.Settings\$TetherSettingsActivity"),
        Intent("android.settings.TETHER_SETTINGS"),
        Intent(Settings.ACTION_WIRELESS_SETTINGS),
        Intent(Settings.ACTION_SETTINGS),
    )
    for (intent in attempts) {
        try {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
            return true
        } catch (e: Exception) {
            // not here on this phone: try the next place
        }
    }
    return false
}
