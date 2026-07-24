# HJP — AI 명함 관리 앱

명함 사진 → 온디바이스 OCR → DB 저장 → Single ReAct Agent(온디바이스 LLM)가
자연어로 명함 검색·메일 초안·일정 등록 등을 수행하는 Android 앱.
팀 프로젝트이며 팀원 전원이 앱 개발 초심자. 이 세션 사용자의 담당은
`create_calendar_event`, `open_compose` 도구 (구현 완료).

## 빌드

PowerShell에서 `JAVA_HOME`이 비어 있으므로 Android Studio JBR을 지정해야 함:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"; .\gradlew.bat :app:assembleDebug --console=plain
```

- Kotlin 2.2 / AGP 9.2 / compileSdk 36 / **minSdk 24** / Jetpack Compose (Material3)
- minSdk 24 제약: `java.time` 사용 불가 (desugaring 미설정) → `java.text.SimpleDateFormat` 사용
- IDE 진단이 새 파일을 못 잡아 가짜 Unresolved reference를 내는 경우가 있음 — 실제 빌드로 검증할 것

## 기술 스택 (팀 결정사항)

- 에이전트: Single ReAct Agent, 도구 9개 예정
- 온디바이스 LLM: Gemma 4 E2B (LiteRT-LM, `LlmRole.Chat` 1순위 — 2026-07-23 연동, 실기기 검증 전), 임베딩: EmbeddingGemma 300M
- 검색: 키워드(정형 DB) + 시맨틱(BM25 + Dense + RRF + Reranker) — 다른 팀원 담당

## 아키텍처: 에이전트 도구 시스템

`app/src/main/java/com/example/hjp/agent/tools/`

- `AgentTool.kt` — 도구 인터페이스: `name`, `declaration`(JSON Schema, Gemini/OpenAI function declaration 호환), `suspend execute(args: JSONObject): String`
- `ToolRegistry.kt` — 도구 등록, `declarationsJson()`(시스템 프롬프트 삽입용), `dispatch()`(tool call 실행)
- `CreateCalendarEventTool.kt`, `OpenComposeTool.kt` — 구현 완료
- `MainActivity.kt` — 현재는 도구 테스트 화면 (tool call JSON 직접 입력·실행). 에이전트 루프 완성 시 교체 예정

## 도구 작성 컨벤션 (반드시 유지)

1. **에러도 예외가 아닌 JSON 반환**: `ToolResults.error("...")` — LLM이 보고 재시도/되묻기 할 수 있게. 예외를 던지면 ReAct 루프가 끊김
2. **결과 메시지는 사실만**: Intent 기반 도구는 "등록 화면을 열었다"이지 "등록했다"가 아님 — 후자는 LLM의 거짓 완료 보고를 유발
3. **declaration의 description에 형식 예시 포함**: 소형 모델(Gemma)용. 날짜는 `yyyy-MM-ddTHH:mm` 고정, 상대 날짜는 `get_current_datetime` 먼저 호출하라는 힌트 포함
4. **시스템 통합은 Intent 우선** (직접 Provider 쓰기 X): 권한 불필요 + 사용자가 최종 확인하는 안전장치. tool call의 최종 실행(저장/전송)은 사용자 몫
5. JSON은 Android 내장 `org.json` 사용 (외부 의존성 추가 X), 주석은 한국어

## 테스트 환경

- AVD: `Pixel_8_API_36` (Google Play 이미지, cmdline-tools로 생성됨)
- 실행: `& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd Pixel_8_API_36`
- 앱 설치·실행: `.\gradlew.bat :app:installDebug` 후 `adb shell am start -n com.example.hjp/.MainActivity`
- 스크린샷: `adb exec-out screencap -p > file`은 PowerShell 리다이렉트가 바이너리를 깨뜨림 — `adb shell screencap -p /sdcard/s.png` 후 `adb pull` 사용
- 캘린더(구글 캘린더)·Gmail은 구글 계정 로그인 필요. 메시지(SMS) 앱은 계정 없이 동작
- 검증 완료 (2026-06-05): open_compose(sms) E2E 통과, create_calendar_event는 Intent 발화 및 구글 캘린더 수신까지 확인(dumpsys), 로그인 이후 UI는 미확인

## 문서

- `README.md` — 초심자 팀원용 상세 가이드 (도구 추가 방법, tool call/result 포맷). 도구 시스템 구조를 바꾸면 README도 같이 갱신할 것
