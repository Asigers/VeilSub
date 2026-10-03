package com.veilsub.android.state

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class CaptureStateMachineTest {
    @Test
    fun happyPathReachesAudioCaptureReadyAndStops() {
        val machine = CaptureStateMachine()

        machine.transition(CaptureStatus.REQUESTING_PERMISSION)
        machine.transition(CaptureStatus.STARTING_CAPTURE)
        machine.transition(CaptureStatus.AUDIO_CAPTURE_READY)
        machine.transition(CaptureStatus.STOPPING)
        machine.transition(CaptureStatus.IDLE)

        assertEquals(CaptureStatus.IDLE, machine.state.status)
    }

    @Test
    fun invalidTransitionIsRejected() {
        val machine = CaptureStateMachine()

        assertThrows(IllegalArgumentException::class.java) {
            machine.transition(CaptureStatus.CAPTURING)
        }
    }
}
