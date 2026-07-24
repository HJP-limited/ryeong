# Real Device Test

This branch is configured for 3 on-device models, split by role:

- `embeddinggemma-300m.tflite` — embedding (keyword+semantic hybrid search)
- FunctionGemma 270M LiteRT-LM (`functiongemma_270m.litertlm`) — tool-calling role
- Gemma 4 E2B IT LiteRT-LM (`gemma-4-E2B-it.litertlm`) — chat/RAG answer role (fallback: `gemma3-1b-it-int4.litertlm`, `gemma3-270m-it-q8.litertlm`)
- Room FTS + vector RRF search

## Model Files

For real-device testing, keep large models out of the APK and push them after install.

The EmbeddingGemma runtime is the AI Edge RAG SDK (GemmaEmbeddingModel) and needs TWO files:

```text
/sdcard/Android/data/com.example.hjp/files/models/embeddinggemma-300m.tflite
/sdcard/Android/data/com.example.hjp/files/models/sentencepiece.model
```

Both come from the `litert-community/embeddinggemma-300m` Hugging Face repo.
Note: the RAG SDK ships arm64-only native libs — embedding will not run on an x86_64 emulator.

The FunctionGemma 270M LiteRT-LM model (tool-calling) is expected at:

```text
/sdcard/Android/data/com.example.hjp/files/models/functiongemma_270m.litertlm
```

The Gemma 4 E2B IT LiteRT-LM model (chat/RAG answers) is expected at:

```text
/sdcard/Android/data/com.example.hjp/files/models/gemma-4-E2B-it.litertlm
```

The app also checks its private files directory:

```text
/data/data/com.example.hjp/files/models/embeddinggemma-300m.tflite
/data/data/com.example.hjp/files/models/functiongemma_270m.litertlm
/data/data/com.example.hjp/files/models/gemma-4-E2B-it.litertlm
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
& "$env:ANDROID_HOME\platform-tools\adb.exe" push ..\models\legacy\embeddinggemma-300m.tflite /sdcard/Android/data/com.example.hjp/files/models/embeddinggemma-300m.tflite
# Optional, when you have the FunctionGemma file:
# & "$env:ANDROID_HOME\platform-tools\adb.exe" push C:\path\to\functiongemma_270m.litertlm /sdcard/Android/data/com.example.hjp/files/models/functiongemma_270m.litertlm
# Optional, when you have the Gemma 4 E2B IT file:
# & "$env:ANDROID_HOME\platform-tools\adb.exe" push C:\path\to\gemma-4-E2B-it.litertlm /sdcard/Android/data/com.example.hjp/files/models/gemma-4-E2B-it.litertlm
& "$env:ANDROID_HOME\platform-tools\adb.exe" shell am start -n com.example.hjp/.MainActivity
```

Open the app and press `Diagnostics`.

Expected real-device result:

```json
{
  "active_embedding_model_backed": true,
  "embedding_dimensions": 768
}
```

If model push fails with a permission error, open the app once first, then rerun the `mkdir` and `push` commands. Android creates the app-specific external directory after install/app start.

## Temporary Sharing Options

For one phone next to the development PC, use USB install. This is fastest.

For another tester, use one of these:

- Send `app/build/outputs/apk/debug/app-debug.apk` directly and allow "install unknown apps" on the phone.
- Send `embeddinggemma-300m.tflite` to the phone Downloads folder, open the app, press `임베딩 가져오기`, and choose the file.
- Send `functiongemma_270m.litertlm` the same way, press `Tool LLM 가져오기`, and choose the file.
- Send `gemma-4-E2B-it.litertlm` the same way, press `Chat LLM 가져오기`, and choose the file.
- Use Firebase App Distribution for a small tester group.
- Use Google Play Internal App Sharing or Internal Testing if the app is already connected to a Play Console project.

Debug APKs are signed with the local debug key and are fine for temporary device testing. Do not use them for public release.

## No USB Cable Flow

1. Send `app/build/outputs/apk/debug/app-debug.apk` to the phone.
2. Install it after enabling "install unknown apps" for the app used to open the APK.
3. Send `models/legacy/embeddinggemma-300m.tflite` to the phone, usually into Downloads.
4. Open HJP, press `임베딩 가져오기`, and select `embeddinggemma-300m.tflite`.
5. Press `모델 상태 다시 확인`.
6. If you have FunctionGemma, send `functiongemma_270m.litertlm`, press `Tool LLM 가져오기`, and select it.
7. If you have Gemma 4 E2B IT, send `gemma-4-E2B-it.litertlm`, press `Chat LLM 가져오기`, and select it.

Embedding search intentionally has no fallback. If Diagnostics does not show `active_embedding_model_backed: true`, search will return an error.
