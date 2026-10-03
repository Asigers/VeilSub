package com.veilsub.android.capture

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class PcmResamplerTest {
    @Test
    fun passthroughAt16kKeepsPcmBytes() {
        val input = shortsToBytes(shortArrayOf(1, -2, 3, -4))
        val resampler = Pcm16MonoResampler(16_000)

        assertArrayEquals(input, resampler.process(input))
    }

    @Test
    fun resamples100ms48kFrameToAbout100ms16k() {
        val samples = ShortArray(4_800) { index -> (index % 1_000).toShort() }
        val input = shortsToBytes(samples)
        val resampler = Pcm16MonoResampler(48_000)

        val output = resampler.process(input)

        assertEquals(1_600 * 2, output.size)
    }

    @Test
    fun keepsContinuityAcrossFrames() {
        val first = ShortArray(4_800) { 1_000 }
        val second = ShortArray(4_800) { 2_000 }
        val resampler = Pcm16MonoResampler(48_000)

        val firstOutput = resampler.process(shortsToBytes(first))
        val secondOutput = resampler.process(shortsToBytes(second))

        assertEquals(3_200, firstOutput.size)
        assertEquals(3_200, secondOutput.size)
    }

    private fun shortsToBytes(samples: ShortArray): ByteArray {
        return ByteBuffer.allocate(samples.size * 2)
            .order(ByteOrder.LITTLE_ENDIAN)
            .also { buffer -> samples.forEach(buffer::putShort) }
            .array()
    }
}
