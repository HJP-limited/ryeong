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
$apkSize = (Get-Item $apk).Length / 1MB
"APK: {0:N1} MB" -f $apkSize
# 네이티브 라이브러리(litertlm/gecko/gemma 임베딩 등)가 88MB 쯤 된다. 이게 빠지면
# APK 가 갑자기 작아지고 그 빌드는 LLM 이 안 뜬다 — OneDrive 파일 잠금으로
# mergeDebugNativeLibs 가 조용히 실패한 전력이 있어서 크기로 감지한다.
if ($apkSize -lt 130) {
    Write-Warning "APK 가 130MB 미만입니다. 네이티브 라이브러리 누락 의심 — app/build 를 지우고 다시 빌드하세요."
}

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
