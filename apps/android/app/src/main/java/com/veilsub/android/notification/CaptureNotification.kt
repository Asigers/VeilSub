package com.veilsub.android.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.veilsub.android.R
import com.veilsub.android.capture.SubtitleCaptureService

object CaptureNotification {
    const val NOTIFICATION_ID = 1001
    private const val CHANNEL_ID = "veilsub_live_subtitles"

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.capture_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    fun build(context: Context): Notification {
        ensureChannel(context)

        val stopIntent = Intent(context, SubtitleCaptureService::class.java)
            .setAction(SubtitleCaptureService.ACTION_STOP)
        val stopPendingIntent = PendingIntent.getService(
            context,
            1,
            stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        return Notification.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(context.getString(R.string.capture_notification_title))
            .setContentText(context.getString(R.string.capture_notification_text))
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .addAction(
                android.R.drawable.ic_media_pause,
                context.getString(R.string.stop),
                stopPendingIntent,
            )
            .build()
    }
}
