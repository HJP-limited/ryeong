$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:ANDROID_HOME = "C:\Users\babie\AppData\Local\Android\Sdk"
$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"

& .\gradlew.bat :app:assembleDebug --no-daemon
& $adb devices -l
& $adb install -r app\build\outputs\apk\debug\app-debug.apk
& $adb shell mkdir -p /sdcard/Android/data/com.example.hjp/files/models

$embedding = Join-Path $repo "..\models\legacy\embeddinggemma_quant.tflite"
if (Test-Path $embedding) {
    & $adb push $embedding /sdcard/Android/data/com.example.hjp/files/models/embeddinggemma_quant.tflite
} else {
    Write-Warning "EmbeddingGemma model not found at $embedding"
}

$functionGemma = Join-Path $repo "..\models\functiongemma_270m.litertlm"
if (Test-Path $functionGemma) {
    & $adb push $functionGemma /sdcard/Android/data/com.example.hjp/files/models/functiongemma_270m.litertlm
} else {
    Write-Warning "FunctionGemma model not found at $functionGemma. Put it there or push it manually."
}

& $adb shell am start -n com.example.hjp/.MainActivity

Write-Host "Open the app and press Diagnostics."
