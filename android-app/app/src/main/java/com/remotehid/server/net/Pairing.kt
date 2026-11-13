package com.remotehid.server.net

import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.Callable
import java.util.concurrent.ExecutorCompletionService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** One address the QR code listed, and why it failed (null = it worked). */
data class Attempt(val host: String, val error: Throwable?)

data class PairingOutcome(val winner: String?, val failures: List<Attempt>)

/** Thrown by an attempt that reached the computer second: another address already won, so this one must not announce again. */
class LostRace : Exception("another address answered first")

/**
 * Tries every address the QR code listed AT THE SAME TIME. One after the other, a stale address cost a full connection timeout
 * before the next was even tried (3 s each), and the error shown was only the last one's.
 *
 * [tryOne] connects to the host and, before it writes anything, must call `claim()`: only the first caller gets true, and the
 * others must throw [LostRace] instead of announcing (the computer would otherwise be told about this phone twice). An attempt
 * that claimed and then failed gives the claim back, so another address can still win.
 */
fun tryAllHosts(hosts: List<String>, tryOne: (host: String, claim: () -> Boolean) -> Unit): PairingOutcome {
    val unique = hosts.distinct()
    if (unique.isEmpty()) return PairingOutcome(null, emptyList())
    val claimed = AtomicBoolean(false)
    val pool = Executors.newFixedThreadPool(unique.size)
    try {
        val done = ExecutorCompletionService<Attempt>(pool)
        for (host in unique) {
            done.submit(Callable<Attempt> {
                var mine = false
                val claim = {
                    val first = claimed.compareAndSet(false, true)
                    if (first) mine = true
                    first
                }
                try {
                    tryOne(host, claim)
                    Attempt(host, null)
                } catch (e: Exception) {
                    if (mine) claimed.set(false)
                    Attempt(host, e)
                }
            })
        }
        val failures = ArrayList<Attempt>()
        for (i in unique.indices) {
            val attempt = done.take().get()
            when {
                attempt.error == null -> return PairingOutcome(attempt.host, failures)
                attempt.error is LostRace -> Unit
                else -> failures.add(attempt)
            }
        }
        return PairingOutcome(null, failures)
    } finally {
        pool.shutdownNow()
    }
}

/** What a connection error means for the person, in a few words. */
fun failureReason(error: Throwable?): String {
    val message = error?.message.orEmpty()
    return when {
        message.contains("ECONNREFUSED", ignoreCase = true) || message.contains("refused", ignoreCase = true) ->
            "refused: the computer is there, but the desktop app is not listening (is it open?)"
        error is SocketTimeoutException || message.contains("ETIMEDOUT", ignoreCase = true) || message.contains("timed out", ignoreCase = true) ->
            "no answer: not on this network, or a firewall or the router blocks it"
        error is NoRouteToHostException || message.contains("No route to host", ignoreCase = true) || message.contains("EHOSTUNREACH") ->
            "no route to that address from this phone"
        message.contains("Network is unreachable", ignoreCase = true) || message.contains("ENETUNREACH") ->
            "this phone has no way to reach that network"
        error is UnknownHostException -> "not a valid address"
        message.isNotBlank() -> message
        else -> "failed"
    }
}

/** Whether two IPv4 addresses share their first three numbers: the size of almost every home, hotspot and cable network. */
fun sameSubnet24(a: String, b: String): Boolean {
    val x = a.split('.')
    val y = b.split('.')
    return x.size == 4 && y.size == 4 && x.take(3) == y.take(3)
}

/**
 * The message when no address worked: every address tried with its own reason, the addresses this phone is on, and what to do.
 * The most common cause is an address that is no longer the computer's (the desktop app redraws its QR code when its addresses
 * change, but a code scanned earlier is stale), which shows up as "none of them is on this phone's network".
 */
fun explainPairingFailure(failures: List<Attempt>, phone: List<LocalAddress>, port: Int): String {
    val lines = ArrayList<String>()
    lines.add("Pairing failed. The QR code sent this phone to:")
    for (attempt in failures) lines.add("  ${attempt.host}:$port  ${failureReason(attempt.error)}")
    lines.add(
        if (phone.isEmpty()) "This phone has no Wi-Fi or cable address right now."
        else "This phone is on: " + phone.joinToString(", ") { "${it.ip} (${if (it.kind == LinkKind.OTHER) it.ifName else it.kind.label})" },
    )
    val shared = failures.any { f -> phone.any { sameSubnet24(f.host, it.ip) } }
    val reasons = failures.map { failureReason(it.error) }
    lines.add(
        when {
            phone.isNotEmpty() && !shared ->
                "None of those addresses is on this phone's network. Check the addresses under the QR code on the computer and scan it again " +
                    "(it updates by itself when the computer's network changes)."
            reasons.any { it.startsWith("refused") } ->
                "Open the desktop app on the computer, then scan again."
            else ->
                "Same network but no answer: a firewall on the computer may block port $port, or the router keeps devices apart (guest Wi-Fi)."
        },
    )
    lines.add("You can also press Find phone on the computer: it connects to this phone directly and needs no QR code.")
    return lines.joinToString("\n")
}
