package com.remotehid.server.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class PairingTest {

    private val timeout = SocketTimeoutException("failed to connect to /192.168.0.105 (port 8766) from /192.168.0.101 (port 43910) after 3000ms")

    @Test
    fun `the address that answers wins and the ones that did not are listed as failures`() {
        val outcome = tryAllHosts(listOf("192.168.0.105", "192.168.43.17", "192.168.42.17")) { host, claim ->
            if (host != "192.168.43.17") throw timeout
            assertTrue(claim())
        }
        assertEquals("192.168.43.17", outcome.winner)
    }

    @Test
    fun `when every address fails each failure is kept with its own reason`() {
        val outcome = tryAllHosts(listOf("a", "b", "c")) { host, _ ->
            when (host) {
                "a" -> throw timeout
                "b" -> throw ConnectException("failed to connect: isConnected failed: ECONNREFUSED (Connection refused)")
                else -> throw NoRouteToHostException("No route to host")
            }
        }
        assertNull(outcome.winner)
        assertEquals(listOf("a", "b", "c"), outcome.failures.map { it.host }.sorted())
        assertTrue(failureReason(outcome.failures.first { it.host == "a" }.error).startsWith("no answer"))
        assertTrue(failureReason(outcome.failures.first { it.host == "b" }.error).startsWith("refused"))
        assertTrue(failureReason(outcome.failures.first { it.host == "c" }.error).startsWith("no route"))
    }

    @Test
    fun `no address at all is not a crash`() {
        assertEquals(PairingOutcome(null, emptyList()), tryAllHosts(emptyList()) { _, _ -> throw AssertionError("nothing to try") })
    }

    @Test
    fun `an address listed twice is tried once`() {
        val tries = AtomicInteger()
        tryAllHosts(listOf("10.0.0.2", "10.0.0.2", "10.0.0.2")) { _, claim -> tries.incrementAndGet(); claim() }
        assertEquals(1, tries.get())
    }

    @Test
    fun `two addresses that both answer announce only once`() {
        val bothThere = CountDownLatch(2)
        val announces = AtomicInteger()
        val outcome = tryAllHosts(listOf("192.168.0.105", "192.168.42.17")) { _, claim ->
            bothThere.countDown()
            bothThere.await(5, TimeUnit.SECONDS)          // both have connected before either may announce
            if (!claim()) throw LostRace()
            announces.incrementAndGet()
        }
        assertEquals(1, announces.get())
        assertTrue(outcome.winner != null)
        assertTrue(outcome.failures.isEmpty())             // the one that lost is not reported as a failure
    }

    @Test
    fun `an address that claimed and then failed lets another one win`() {
        val firstFailed = CountDownLatch(1)
        val outcome = tryAllHosts(listOf("first", "second")) { host, claim ->
            if (host == "first") {
                assertTrue(claim())
                firstFailed.countDown()
                throw IOException("connection reset while writing")
            }
            firstFailed.await(5, TimeUnit.SECONDS)
            Thread.sleep(50)                               // the failed attempt gives its claim back
            if (!claim()) throw LostRace()
        }
        assertEquals("second", outcome.winner)
    }

    @Test
    fun `a slow dead address does not hold up one that answers`() {
        val started = System.nanoTime()
        val outcome = tryAllHosts(listOf("dead", "alive")) { host, claim ->
            if (host == "dead") Thread.sleep(4000)
            assertTrue(claim())
        }
        assertEquals("alive", outcome.winner)
        assertTrue("took ${(System.nanoTime() - started) / 1_000_000} ms", (System.nanoTime() - started) < 2_000_000_000L)
    }

    @Test
    fun `reasons are plain words`() {
        assertTrue(failureReason(timeout).startsWith("no answer"))
        assertTrue(failureReason(ConnectException("isConnected failed: ETIMEDOUT (Connection timed out)")).startsWith("no answer"))
        assertTrue(failureReason(ConnectException("isConnected failed: ECONNREFUSED (Connection refused)")).startsWith("refused"))
        assertTrue(failureReason(IOException("connect failed: ENETUNREACH (Network is unreachable)")).startsWith("this phone has no way"))
        assertTrue(failureReason(UnknownHostException("nope")).startsWith("not a valid"))
        assertEquals("something odd", failureReason(IOException("something odd")))
        assertEquals("failed", failureReason(null))
    }

    @Test
    fun `same subnet means the first three numbers match`() {
        assertTrue(sameSubnet24("192.168.0.105", "192.168.0.101"))
        assertFalse(sameSubnet24("192.168.0.105", "192.168.1.101"))
        assertFalse(sameSubnet24("192.168.0.105", "garbage"))
        assertFalse(sameSubnet24("192.168.0", "192.168.0.1"))
    }

    private val wifi = LocalAddress("wlan0", "192.168.0.101", LinkKind.WIFI)

    @Test
    fun `a stale address is named as the likely cause when none is on the phones network`() {
        val text = explainPairingFailure(listOf(Attempt("10.20.30.7", timeout)), listOf(wifi), 8766)
        assertTrue(text.contains("10.20.30.7:8766"))
        assertTrue(text.contains("This phone is on: 192.168.0.101 (Wi-Fi)"))
        assertTrue(text.contains("None of those addresses is on this phone's network"))
        assertTrue(text.contains("scan it again"))
        assertTrue(text.contains("Find phone"))
    }

    @Test
    fun `an address on the same network that does not answer points at a firewall or the router`() {
        val text = explainPairingFailure(listOf(Attempt("192.168.0.105", timeout)), listOf(wifi), 8766)
        assertTrue(text.contains("192.168.0.105:8766  no answer"))
        assertTrue(text.contains("firewall on the computer may block port 8766"))
        assertFalse(text.contains("None of those addresses"))
    }

    @Test
    fun `a refusal says to open the desktop app`() {
        val refused = ConnectException("failed: ECONNREFUSED (Connection refused)")
        val text = explainPairingFailure(listOf(Attempt("192.168.0.105", refused)), listOf(wifi), 8766)
        assertTrue(text.contains("Open the desktop app"))
    }

    @Test
    fun `every address tried is listed with the port`() {
        val text = explainPairingFailure(listOf(Attempt("192.168.0.105", timeout), Attempt("192.168.42.17", timeout)), listOf(wifi), 8766)
        assertTrue(text.contains("192.168.0.105:8766"))
        assertTrue(text.contains("192.168.42.17:8766"))
    }

    @Test
    fun `a phone with no address says so`() {
        val text = explainPairingFailure(listOf(Attempt("192.168.0.105", timeout)), emptyList(), 8766)
        assertTrue(text.contains("This phone has no Wi-Fi or cable address right now."))
    }
}
