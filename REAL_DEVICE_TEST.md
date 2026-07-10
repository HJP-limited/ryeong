# Real Device Test

This branch is configured for:

- FunctionGemma 270M LiteRT-LM
- `embeddinggemma_quant.tflite`
- Room FTS + vector RRF search

## Model Files

For real-device testing, keep large models out of the APK and push them after install.

The EmbeddingGemma TFLite model is expected at:

```text
/sdcard/Android/data/com.example.hjp/files/models/embeddinggemma_quant.tflite
```

The FunctionGemma 270M LiteRT-LM model is expected at either:

```text
/sdcard/Android/data/com.example.hjp/files/models/functiongemma_270m.litertlm
```

The app also checks its private files directory:

```text
/data/data/com.example.hjp/files/models/embeddinggemma_quant.tflite
/data/data/com.example.hjp/files/models/functiongemma_270m.litertlm
```

Large model files are ignored by git.

## USB Install

Enable Developer Options and USB debugging on an Android arm64 device, then run:

```powershell
.\scripts\install_real_device_debug.ps1
```

Manual equivalent:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:ANDROID_HOME='C:\Users\babie\AppData\Local\Android\Sdk'
.\gradlew.bat :app:assembleDebug --no-daemon
& "$env:ANDROID_HOME\platform-tools\adb.exe" devices -l
& "$env:ANDROID_HOME\platform-tools\adb.exe" install -r app\build\outputs\apk\debug\app-debug.apk
& "$env:ANDROID_HOME\platform-tools\adb.exe" shell mkdir -p /sdcard/Android/data/com.example.hjp/files/models
& "$env:ANDROID_HOME\platform-tools\adb.exe" push ..\models\legacy\embeddinggemma_quant.tflite /sdcard/Android/data/com.example.hjp/files/models/embeddinggemma_quant.tflite
# Optional, when you have the FunctionGemma file:
# & "$env:ANDROID_HOME\platform-tools\adb.exe" push C:\path\to\functiongemma_270m.litertlm /sdcard/Android/data/com.example.hjp/files/models/functiongemma_270m.litertlm
& "$env:ANDROID_HOME\platform-tools\adb.exe" shell am start -n com.example.hjp/.MainActivity
```

Open the app and press `Diagnostics`.

Expected real-device result:

```json
{
  "active_embedding_model_backed": true,
  "mediapipe_model_backed": true,
  "embedding_dimensions": 768
}
```

If `active_embedding_provider` is `LocalHashEmbeddingProvider`, EmbeddingGemma did not load.

If model push fails with a permission error, open the app once first, then rerun the `mkdir` and `push` commands. Android creates the app-specific external directory after install/app start.

## Temporary Sharing Options

For one phone next to the development PC, use USB install. This is fastest.

For another tester, use one of these:

- Send `app/build/outputs/apk/debug/app-debug.apk` directly and allow "install unknown apps" on the phone.
- Use Firebase App Distribution for a small tester group.
- Use Google Play Internal App Sharing or Internal Testing if the app is already connected to a Play Console project.

Debug APKs are signed with the local debug key and are fine for temporary device testing. Do not use them for public release.
