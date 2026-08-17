# 실기기(갤럭시 S21급) 디버그 설치 스크립트.
#
# 모델은 **폰에 이미 있으면 다시 밀지 않는다.** 3.1GB 를 USB 로 매번 보내면 몇 분씩
# 걸리는데, 대부분은 바뀌지 않는다. 크기가 같으면 같은 파일로 보고 건너뛴다.
# 강제로 다시 보내려면 -ForceModels 를 준다.
param(
    [switch]$ForceModels,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:ANDROID_HOME = "C:\Users\babie\AppData\Local\Android\Sdk"
$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"

$deviceModelDir = "/sdcard/Android/data/com.example.hjp/files/models"

if (-not $SkipBuild) {
    & .\gradlew.bat :app:assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "빌드 실패" }
}

$apk = "app\build\outputs\apk\debug\app-debug.apk"
"APK: {0:N1} MB" -f ((Get-Item $apk).Length / 1MB)

# 네이티브 라이브러리가 빠진 APK 는 LLM 이 안 뜬다 — OneDrive 파일 잠금으로
# mergeDebugNativeLibs 가 조용히 실패한 전력이 있다.
# **총 크기로 판단하지 않는다.** 시드 데이터(카드 수)에 따라 총량이 크게 달라져서
# 임계값이 금방 낡는다(5000장 -> 1000장으로 줄이자 16.9MB -> 3.4MB). 대신 결정적인
# 파일이 실제로 들어갔는지 이름으로 확인한다.
$required = @("liblitertlm_jni.so", "libgemma_embedding_model_jni.so")
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $apk))
try {
    $names = $zip.Entries | ForEach-Object { Split-Path $_.FullName -Leaf }
    foreach ($lib in $required) {
        if ($names -notcontains $lib) {
            throw "$lib 가 APK 에 없습니다. app/build 를 지우고 다시 빌드하세요(OneDrive 잠금 의심)."
        }
    }
    "네이티브 라이브러리 확인: $($required -join ', ')"
} finally { $zip.Dispose() }

& $adb devices -l
& $adb install -r $apk
if ($LASTEXITCODE -ne 0) { throw "설치 실패" }

& $adb shell mkdir -p $deviceModelDir

# 로컬 경로 -> 폰에 올라갈 이름.
# embeddinggemma 는 앱이 찾는 이름이 embeddinggemma-300m.tflite 이고 토크나이저
# (sentencepiece.model)와 한 세트다. 로컬 legacy/embeddinggemma_quant.tflite 는
# 이름도 크기도 다른 구버전이라 쓰지 않는다.
$models = @(
    @{ Local = "..\models\gemma-4-E2B-it.litertlm";     Name = "gemma-4-E2B-it.litertlm" },
    @{ Local = "..\models\functiongemma_270m.litertlm"; Name = "functiongemma_270m.litertlm" }
)

foreach ($m in $models) {
    $path = Join-Path $repo $m.Local
    if (-not (Test-Path $path)) {
        Write-Warning "$($m.Name) 없음: $path — 폰에 이미 있으면 무시해도 됩니다."
        continue
    }
    $localSize = (Get-Item $path).Length
    $remote = "$deviceModelDir/$($m.Name)"
    $remoteSize = (& $adb shell "stat -c %s '$remote' 2>/dev/null").Trim()

    if (-not $ForceModels -and $remoteSize -eq "$localSize") {
        "건너뜀 (동일): $($m.Name)  {0:N0} bytes" -f $localSize
        continue
    }
    "전송: $($m.Name)  {0:N0} bytes" -f $localSize
    & $adb push $path $remote
}

# 임베딩 모델 + 토크나이저는 폰에 있는 것을 그대로 쓴다(로컬에 대응 파일이 없다).
foreach ($n in @("embeddinggemma-300m.tflite", "sentencepiece.model")) {
    $size = (& $adb shell "stat -c %s '$deviceModelDir/$n' 2>/dev/null").Trim()
    if ($size) { "폰에 있음: $n  $size bytes" } else { Write-Warning "$n 이 폰에 없습니다 — 온디바이스 임베딩이 안 됩니다." }
}

& $adb shell am start -n com.example.hjp/.MainActivity
Write-Host "앱을 열고 Diagnostics 를 눌러 모델 상태를 확인하세요."
