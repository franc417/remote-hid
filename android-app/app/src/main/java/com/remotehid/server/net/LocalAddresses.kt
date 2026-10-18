package com.remotehid.server.net

import java.net.Inet4Address
import java.net.NetworkInterface

/** How this phone is reachable on one network link. */
enum class LinkKind(val label: String, val rank: Int) {
    USB("USB cable", 0),
    WIFI("Wi-Fi", 1),
    HOTSPOT("Hotspot", 2),
    OTHER("", 3),
}

data class LocalAddress(val ifName: String, val ip: String, val kind: LinkKind)

/**
 * Which kind of link an Android network interface is, or null for ones that
 * are never a way for a desktop to reach this phone (loopback, mobile data,
 * VPNs, dummy interfaces).
 */
fun classifyInterface(name: String): LinkKind? {
    val n = name.lowercase()
    val ignored = listOf("lo", "rmnet", "ccmni", "v4-", "dummy", "tun", "tap", "wg", "ipsec", "p2p", "clat", "sit", "ip6")
    if (ignored.any { n.startsWith(it) }) return null
    return when {
        // A USB tether shows up as rndis0 / usb0 / ncm0; eth* is a USB Ethernet adapter.
        n.startsWith("rndis") || n.startsWith("usb") || n.startsWith("ncm") || n.startsWith("eth") -> LinkKind.USB
        n.startsWith("wlan") || n.startsWith("wifi") -> LinkKind.WIFI
        n.startsWith("ap") || n.startsWith("swlan") -> LinkKind.HOTSPOT
        else -> LinkKind.OTHER
    }
}

/**
 * Every IPv4 address this phone can be reached on, USB first. Before this the
 * app only knew the Wi-Fi address: with Wi-Fi off (or the cable on a different
 * network) it showed "unknown IP" and announced an address the desktop could
 * not reach, which is why USB connections "sometimes" failed.
 */
fun collectLocalAddresses(interfaces: List<NetworkInterface>? = null): List<LocalAddress> {
    val list = interfaces ?: try {
        NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
    } catch (e: Exception) {
        emptyList()
    }
    val found = mutableListOf<LocalAddress>()
    for (nif in list) {
        val up = try { nif.isUp && !nif.isLoopback } catch (e: Exception) { false }
        if (!up) continue
        val kind = classifyInterface(nif.name) ?: continue
        for (addr in nif.inetAddresses) {
            if (addr is Inet4Address && !addr.isLoopbackAddress && !addr.isLinkLocalAddress) {
                found.add(LocalAddress(nif.name, addr.hostAddress ?: continue, kind))
            }
        }
    }
    return found.sortedBy { it.kind.rank }
}

/** The text for the status line. */
fun describeAddresses(addresses: List<LocalAddress>, port: Int): String {
    fun tag(a: LocalAddress) = if (a.kind == LinkKind.OTHER) a.ifName else a.kind.label
    return when (addresses.size) {
        0 -> "No network address yet: join Wi-Fi, or plug in the cable and turn on USB tethering"
        1 -> "Listening on ws://${addresses[0].ip}:$port (${tag(addresses[0])})"
        else -> "Listening on:\n" + addresses.joinToString("\n") { "${tag(it)}  ws://${it.ip}:$port" }
    }
}
