package com.example.hjp.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(
    primary = PastelBlue,
    onPrimary = NavyDeep,
    primaryContainer = NavyPrimary,
    onPrimaryContainer = MistBlue,
    secondary = PastelBlueSoft,
    onSecondary = NavyDeep,
    tertiary = SlateBlue,
)

private val LightColorScheme = lightColorScheme(
    primary = NavyPrimary,
    onPrimary = androidx.compose.ui.graphics.Color.White,
    primaryContainer = MistBlue,
    onPrimaryContainer = NavyDeep,
    secondary = SlateBlue,
    onSecondary = androidx.compose.ui.graphics.Color.White,
    secondaryContainer = MistBlue,
    onSecondaryContainer = NavyDeep,
    tertiary = PastelBlue,
)

@Composable
fun HJPTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    // 기기 배경화면 색을 따라가면 앱 고유 남색이 묻히므로 끈다
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }

        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}