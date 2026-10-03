package com.veilsub.android.settings

data class UserSettings(
    val gatewayUrl: String = "ws://10.0.2.2:8000/v1/live",
    val sourceLanguage: String = "ja-JP",
    val targetLanguage: String = "zh-CN",
    val displayMode: String = "bilingual",
    val fontSizeSp: Int = 21,
    val backgroundOpacityPercent: Int = 72,
    val subtitleDelayMs: Int = 0,
)
