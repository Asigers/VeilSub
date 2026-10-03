package com.veilsub.android.capture

import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.floor
import kotlin.math.roundToInt

class Pcm16MonoResampler(
    private val inputSampleRateHz: Int,
    private val outputSampleRateHz: Int = 16_000,
) {
    init {
        require(inputSampleRateHz > 0)
        require(outputSampleRateHz > 0)
    }

    private val step = inputSampleRateHz.toDouble() / outputSampleRateHz.toDouble()
    private var nextPosition = 0.0
    private var previousSample: Short? = null

    fun process(input: ByteArray, length: Int = input.size): ByteArray {
        if (length <= 1) return ByteArray(0)

        val sampleCount = length / 2
        val decoded = ShortArray(sampleCount)
        val buffer = ByteBuffer.wrap(input, 0, sampleCount * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (index in 0 until sampleCount) {
            decoded[index] = buffer.short
        }

        if (inputSampleRateHz == outputSampleRateHz) {
            return input.copyOf(sampleCount * 2)
        }

        val prefix = previousSample
        val samples = if (prefix == null) {
            decoded
        } else {
            ShortArray(decoded.size + 1).also { combined ->
                combined[0] = prefix
                decoded.copyInto(combined, destinationOffset = 1)
            }
        }

        if (samples.size < 2) {
            previousSample = samples.lastOrNull()
            return ByteArray(0)
        }

        val output = ArrayList<Short>()
        while (nextPosition < samples.lastIndex) {
            val leftIndex = floor(nextPosition).toInt()
            val fraction = nextPosition - leftIndex
            val left = samples[leftIndex].toDouble()
            val right = samples[leftIndex + 1].toDouble()
            val interpolated = left + (right - left) * fraction
            output += interpolated.roundToInt()
                .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
                .toShort()
            nextPosition += step
        }

        nextPosition -= samples.lastIndex
        previousSample = samples.last()

        return ByteBuffer.allocate(output.size * 2)
            .order(ByteOrder.LITTLE_ENDIAN)
            .also { out -> output.forEach(out::putShort) }
            .array()
    }
}
