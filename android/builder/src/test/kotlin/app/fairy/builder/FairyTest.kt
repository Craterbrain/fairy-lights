package app.fairy.builder

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The golden files were written by fairy.py / anim.py; the Kotlin sender must produce the same bytes and pauses. */
class FairyTest {
    private fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }

    private fun check(name: String) {
        val lines = javaClass.classLoader!!.getResourceAsStream("$name.txt")!!.bufferedReader().readLines()
        val head = lines[0].split(" ").map { it.toInt() }
        val (w, h, speed, direction, fx, fy, n) = head
        val frames = (1..n).map { i -> lines[i].split(",").map { it.toInt() }.toIntArray() }
        val expected = lines.drop(n + 1).map { it.split(" ").let { p -> p[0].toLong() to p[1] } }
        val steps = Fairy.uploadSteps(frames, w, h, speed, direction, fx == 1, fy == 1)
        assertEquals("$name: number of writes", expected.size, steps.size)
        steps.forEachIndexed { i, s ->
            assertEquals("$name: write $i bytes", expected[i].second, hex(s.data))
            assertEquals("$name: write $i pause", expected[i].first, s.delayMs)
        }
    }

    private operator fun <T> List<T>.component6() = this[5]
    private operator fun <T> List<T>.component7() = this[6]

    @Test fun threeFrameAnimationMatchesPython() = check("golden_anim")
    @Test fun singlePictureWithFlashEffectMatchesPython() = check("golden_still")
    @Test fun sevenFramesWithBothFlipsMatchesPython() = check("golden_long")

    @Test fun framesCarryTheCaptureChecksum() {
        assertEquals("aa0000aa", hex(Fairy.frame(0x00)))
        assertEquals("aa020101ae", hex(Fairy.power(true)))
        // an all-off picture starts exactly like the vendor app's capture, checksum included
        val first = Fairy.picPackets(1, IntArray(800) { Fairy.OFF })[0]
        assertTrue(hex(first).startsWith("aadaee01" + "0000fe" + "0001fe" + "0002fe"))
        assertEquals("de", hex(first).takeLast(2))   // the checksum the vendor app sent for this packet
    }

    @Test fun elevenPacketsPerFrame() = assertEquals(11, Fairy.picPackets(1, IntArray(800)).size)

    @Test fun rejectsBadProjects() {
        var failed = 0
        try { Fairy.uploadSteps(emptyList(), 40, 20, 50, 0, false, false) } catch (e: IllegalArgumentException) { failed++ }
        try { Fairy.uploadSteps(listOf(IntArray(5)), 40, 20, 50, 0, false, false) } catch (e: IllegalArgumentException) { failed++ }
        try { Fairy.uploadSteps(List(256) { IntArray(800) }, 40, 20, 50, 0, false, false) } catch (e: IllegalArgumentException) { failed++ }
        assertEquals(3, failed)
    }
}
