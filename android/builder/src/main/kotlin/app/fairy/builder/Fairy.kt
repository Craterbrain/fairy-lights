package app.fairy.builder

/** One Bluetooth write, followed by a pause before the next one. */
class Step(val data: ByteArray, val delayMs: Long)

/**
 * The Hello Fairy picture protocol, ported from fairy.py (verified byte for byte against it in FairyTest).
 * frame = AA TYPE LEN payload SUM, where SUM is the low byte of the sum of every earlier byte.
 */
object Fairy {
    const val SERVICE = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
    const val WRITE = "49535343-8841-43f4-a8d4-ecbe34729bb3"
    const val NAME_PREFIX = "Hello Fairy"
    const val OFF = 254
    const val MAX_PAYLOAD = 238          // the light's packets are 242 bytes with the 4 framing bytes

    fun frame(type: Int, payload: ByteArray = ByteArray(0)): ByteArray {
        val body = byteArrayOf(0xAA.toByte(), type.toByte(), payload.size.toByte()) + payload
        return body + (body.sumOf { it.toInt() and 0xFF } and 0xFF).toByte()
    }

    fun power(on: Boolean) = frame(0x02, byteArrayOf(if (on) 1 else 0))

    /** d0: playback settings. kind 0 edit, 1 show static, 2 run animation, 3 new static, 4 save, 6 one-byte colours, 7 new animation. */
    fun picParam(direction: Int, speed: Int, kind: Int, bright: Int = 100) =
        frame(0xD0, byteArrayOf(direction.toByte(), bright.toByte(), speed.toByte(), kind.toByte()))

    /** d7: frame bookkeeping. state 0 new, 1 edit, 2 save, 3 delete. */
    fun picFrameState(num: Int, state: Int) = frame(0xD7, byteArrayOf(num.toByte(), state.toByte()))

    /** da packets for one frame of one-byte colours in LED order. */
    fun picPackets(num: Int, colours: IntArray): List<ByteArray> {
        val per = (MAX_PAYLOAD - 1) / 3
        val out = ArrayList<ByteArray>()
        var i = 0
        while (i < colours.size) {
            val end = minOf(i + per, colours.size)
            val body = ByteArray(1 + (end - i) * 3)
            body[0] = num.toByte()
            var o = 1
            for (led in i until end) {
                body[o++] = (led shr 8).toByte(); body[o++] = led.toByte(); body[o++] = colours[led].toByte()
            }
            out.add(frame(0xDA, body))
            i = end
        }
        return out
    }

    fun ledIndex(x: Int, y: Int, h: Int) = x * h + y

    /** The builder keeps frames in display order (x * h + y); the light wants LED order, optionally mirrored. */
    fun toLedOrder(frame: IntArray, w: Int, h: Int, flipX: Boolean, flipY: Boolean): IntArray {
        val out = IntArray(w * h) { OFF }
        for (x in 0 until w) for (y in 0 until h)
            out[ledIndex(if (flipX) w - 1 - x else x, if (flipY) h - 1 - y else y, h)] = frame[x * h + y]
        return out
    }

    /** Everything the vendor app sends for a picture or animation, in order. frames are already in LED order. */
    fun animationSteps(frames: List<IntArray>, speed: Int, direction: Int): List<Step> {
        val still = frames.size == 1
        val out = ArrayList<Step>()
        fun add(data: ByteArray, delayMs: Long) = out.add(Step(data, delayMs))
        add(picParam(if (still) direction else 0, speed, 6), 100)
        add(picParam(0, speed, if (still) 3 else 7), 100)
        if (!still) add(picFrameState(1, 0), 100)
        add(picParam(0, speed, 0), 100)
        frames.forEachIndexed { i, fr ->
            if (i > 0) { add(picFrameState(i, 2), 100); add(picFrameState(i + 1, 0), 100) }
            picPackets(i + 1, fr).forEach { add(it, 50) }
        }
        if (!still) add(picFrameState(frames.size, 2), 100)
        val runDir = if (still) direction else 1
        add(picParam(runDir, speed, 4), 300)
        add(picParam(runDir, speed, if (still) 1 else 2), 100)
        return out
    }

    /** Power on, then the picture: exactly what builder.py sends for "Send to lights". */
    fun uploadSteps(frames: List<IntArray>, w: Int, h: Int, speed: Int, direction: Int, flipX: Boolean, flipY: Boolean): List<Step> {
        require(frames.size in 1..255) { "need 1 to 255 frames, got ${frames.size}" }
        frames.forEach { require(it.size == w * h) { "frame has ${it.size} pixels, expected ${w * h}" } }
        return listOf(Step(power(true), 150)) +
            animationSteps(frames.map { toLedOrder(it, w, h, flipX, flipY) }, speed, direction)
    }
}
