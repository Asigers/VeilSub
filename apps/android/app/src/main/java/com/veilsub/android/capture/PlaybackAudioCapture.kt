package com.veilsub.android.capture

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.projection.MediaProjection
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.max

class PlaybackAudioCapture(
    private val projection: MediaProjection,
) {
    private var audioRecord: AudioRecord? = null
    private var readJob: Job? = null

    var inputSampleRateHz: Int = 0
        private set

    @SuppressLint("MissingPermission")
    fun start(
        scope: CoroutineScope,
        onPcm16kFrame: (ByteArray) -> Unit,
        onFailure: (Throwable) -> Unit,
    ) {
        check(audioRecord == null) { "Playback capture is already active" }

        val (record, sampleRate) = createAudioRecord()
        audioRecord = record
        inputSampleRateHz = sampleRate

        val resampler = Pcm16MonoResampler(
            inputSampleRateHz = sampleRate,
            outputSampleRateHz = TARGET_SAMPLE_RATE_HZ,
        )
        val readBuffer = ByteArray(sampleRate / 10 * BYTES_PER_SAMPLE)

        record.startRecording()

        readJob = scope.launch {
            try {
                while (isActive) {
                    val read = record.read(
                        readBuffer,
                        0,
                        readBuffer.size,
                        AudioRecord.READ_BLOCKING,
                    )
                    when {
                        read > 0 -> {
                            val frame = resampler.process(readBuffer, read)
                            if (frame.isNotEmpty()) {
                                onPcm16kFrame(frame)
                            }
                        }
                        read == 0 -> Unit
                        else -> error("AudioRecord.read failed with code $read")
                    }
                }
            } catch (error: Throwable) {
                if (isActive) {
                    onFailure(error)
                }
            }
        }
    }

    fun stop() {
        readJob?.cancel()
        readJob = null

        val record = audioRecord
        audioRecord = null
        if (record != null) {
            runCatching {
                if (record.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    record.stop()
                }
            }
            runCatching { record.release() }
        }
    }

    @SuppressLint("MissingPermission")
    private fun createAudioRecord(): Pair<AudioRecord, Int> {
        val captureConfig = AudioPlaybackCaptureConfiguration.Builder(projection)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
            .build()

        val failures = mutableListOf<String>()

        for (sampleRate in INPUT_SAMPLE_RATE_CANDIDATES) {
            val minBuffer = AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minBuffer <= 0) {
                failures += "$sampleRate Hz: unsupported min buffer ($minBuffer)"
                continue
            }

            val frameBytes = sampleRate / 10 * BYTES_PER_SAMPLE
            val bufferBytes = max(minBuffer * 2, frameBytes * 4)

            val attempt = runCatching {
                AudioRecord.Builder()
                    .setAudioPlaybackCaptureConfig(captureConfig)
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(sampleRate)
                            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                            .build(),
                    )
                    .setBufferSizeInBytes(bufferBytes)
                    .build()
            }

            val record = attempt.getOrNull()
            if (record != null && record.state == AudioRecord.STATE_INITIALIZED) {
                return record to sampleRate
            }

            record?.release()
            val reason = attempt.exceptionOrNull()?.message ?: "not initialized"
            failures += "$sampleRate Hz: $reason"
        }

        error(
            "Could not initialize playback AudioRecord. " +
                failures.joinToString(separator = "; "),
        )
    }

    companion object {
        const val TARGET_SAMPLE_RATE_HZ = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private val INPUT_SAMPLE_RATE_CANDIDATES = intArrayOf(48_000, 44_100, 16_000)
    }
}
