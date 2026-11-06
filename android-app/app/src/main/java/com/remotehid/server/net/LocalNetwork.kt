package com.remotehid.server.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket

/** What the QR code from the desktop carries: one or several addresses of the desktop, and its rendezvous port. */
data class Rendezvous(val hosts: List<String>, val port: Int)

/**
 * `192.168.1.5:8766` (one address, as before) or `192.168.1.5,192.168.43.17:8766` (a computer with several networks: the phone
 * tries them in order). Null when the text is not an address list at all.
 */
fun parseRendezvous(text: String): Rendezvous? {
    val trimmed = text.trim()
    val colon = trimmed.lastIndexOf(':')
    if (colon <= 0) return null
    val port = trimmed.substring(colon + 1).toIntOrNull() ?: return null
    if (port !in 1..65535) return null
    val hosts = trimmed.substring(0, colon).split(',').map { it.trim() }.filter { it.isNotEmpty() }
    return if (hosts.isEmpty()) null else Rendezvous(hosts, port)
}

/** An address on a home, hotspot or cable network: where a connection must NOT be sent out over mobile data. */
fun isLocalTarget(address: InetAddress): Boolean = address.isSiteLocalAddress || address.isLinkLocalAddress

/**
 * Outgoing connections from the phone to something on the local network.
 *
 * Android sends a plain connection out over its DEFAULT network. While mobile data is on, and the Wi-Fi the computer is on has no
 * internet (a hotspot whose data ran out, a laptop sharing its Wi-Fi), the default network is the mobile one: the connection to
 * the computer's local address then goes to the mobile network, where it cannot arrive, and pairing fails with "no route" or a
 * timeout. Home Wi-Fi with internet, or mobile data switched off, hid the problem. So a connection to a local address is bound to
 * the Wi-Fi / cable network whose own subnet contains that address, whether or not that network has internet.
 */
object LocalNetwork {
    fun connect(context: Context, host: String, port: Int, timeoutMs: Int = 3000): Socket {
        val target = InetAddress.getByName(host)
        val socket = Socket()
        try {
            if (isLocalTarget(target)) bindToLocalNetwork(context, socket, target)
            socket.connect(InetSocketAddress(target, port), timeoutMs)
            return socket
        } catch (e: Exception) {
            try { socket.close() } catch (ignored: IOException) { /* already closed */ }
            throw e
        }
    }

    @Suppress("DEPRECATION")
    private fun bindToLocalNetwork(context: Context, socket: Socket, target: InetAddress) {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return
        for (network in manager.allNetworks) {
            val capabilities = manager.getNetworkCapabilities(network) ?: continue
            val local = capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
            if (!local) continue
            val properties = manager.getLinkProperties(network) ?: continue
            if (properties.routes.any { !it.isDefaultRoute && it.matches(target) }) {
                try {
                    network.bindSocket(socket)
                    return
                } catch (ignored: IOException) {
                    // Try the next network that also contains the address.
                }
            }
        }
        // Nothing matched (for example the phone IS the hotspot): the kernel's own local route is the right one.
    }
}
