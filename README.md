# HJP — AI 명함 관리 앱

명함을 사진으로 찍으면 온디바이스 OCR로 인식해 DB에 저장하고,
AI 에이전트가 자연어 명령("김민준 부장 명함 찾아줘", "그 사람한테 미팅 메일 써줘")을
처리해주는 앱입니다.

## 전체 아키텍처

```
[사용자 자연어 입력]
        ↓
[온디바이스 LLM (Gemma 4 E2B, LiteRT-LM)]   ← 시스템 프롬프트에 "도구 목록" 포함
        ↓
LLM이 판단: "도구를 써야겠다" → tool call JSON 출력
        ↓
[ToolRegistry] 가 JSON을 받아서 해당 도구 실행
        ↓
실행 결과(JSON)를 다시 LLM에게 전달
        ↓
LLM이 결과를 보고 다음 행동 결정 (다른 도구 호출 or 사용자에게 답변)
```

이런 "생각 → 도구 사용 → 결과 관찰 → 다시 생각" 반복 구조를 **ReAct 루프**라고 합니다.
LLM은 직접 캘린더를 열거나 DB를 검색할 수 없기 때문에,
**우리가 만든 도구(Tool)들이 LLM의 손발 역할**을 합니다.

## 프로젝트 구조

```
app/src/main/java/com/example/hjp/
├── agent/tools/                      ← 에이전트 도구들이 모이는 곳
│   ├── AgentTool.kt                  ← ★ 모든 도구가 구현해야 하는 공통 인터페이스
│   ├── ToolRegistry.kt               ← 도구 등록 + LLM tool call 실행(디스패치)
│   ├── CreateCalendarEventTool.kt    ← 캘린더 일정 등록 화면 열기 (구현 완료)
│   └── OpenComposeTool.kt            ← 메일/문자 작성 화면 열기 (구현 완료)
├── MainActivity.kt                   ← 현재는 도구 테스트 화면 (LLM 없이 도구 검증용)
└── ui/theme/                         ← Compose 테마 (자동 생성된 파일)
```

## 실행 방법

1. Android Studio에서 프로젝트 열기 (`File > Open` → HJP 폴더 선택)
2. 처음 열면 Gradle Sync가 자동으로 돌아감 (몇 분 걸릴 수 있음, 하단 상태바 확인)
3. 상단 툴바에서 에뮬레이터 또는 USB로 연결한 실제 기기 선택
4. 초록 ▶(Run) 버튼 클릭

> 💡 **에뮬레이터**: 이 프로젝트용으로 `Pixel_8_API_36` AVD(Google Play 이미지)가 이미 만들어져 있습니다.
> Device Manager 목록에 없다면 직접 만들어도 되는데, 캘린더/메일 앱 테스트를 하려면
> 반드시 **Google Play 지원 이미지**(Play 스토어 아이콘 표시된 것)를 고르세요.
> 기본 AOSP 이미지에는 메일 앱이 없어서 "앱이 설치되어 있지 않습니다" 에러가 정상적으로 뜹니다.

> ⚠️ **구글 캘린더와 Gmail은 구글 계정 로그인이 필요합니다.**
> 에뮬레이터 첫 사용 시: 설정 앱 → `Passwords & accounts` → `Add account` → Google 로그인.
> 메시지(SMS) 앱은 계정 없이 바로 동작합니다.

## 테스트 가이드

앱을 실행하면 **도구 테스트 화면**이 뜹니다:
- "캘린더 예시 / 메일 예시 / 문자 예시" 버튼 → LLM이 출력했다고 가정한 tool call JSON이 입력창에 채워짐
- "실행" 버튼 → 실제로 도구가 실행됨 (캘린더 앱이 열리는 등)
- 결과 영역 → 도구가 LLM에게 돌려줄 결과 JSON 표시

LLM 연동 전에 이 화면으로 각자 만든 도구를 검증하면 됩니다.
입력창의 JSON은 직접 수정할 수 있으므로, "LLM이 실수한 상황"을 만들어 에러 응답도 확인하세요.

### 테스트 체크리스트

**정상 케이스** — 예시 버튼 누르고 그대로 실행:

| # | 테스트 | 기대 결과 |
|---|---|---|
| 1 | 캘린더 예시 → 실행 | 구글 캘린더의 일정 등록 화면이 제목/시간/장소/메모/참석자 채워진 채 열림 |
| 2 | 메일 예시 → 실행 | Gmail 작성 화면이 받는사람/제목/본문 채워진 채 열림 |
| 3 | 문자 예시 → 실행 | 메시지 앱에 번호/본문 채워진 채 열림 |

**에러 케이스** — JSON을 직접 고쳐서 실행 (결과가 LLM이 보고 고칠 수 있을 만큼 친절한지 확인):

| # | 입력 조작 | 기대 결과 |
|---|---|---|
| 4 | `start_time`을 `"내일 2시"`로 변경 | `error` + "yyyy-MM-ddTHH:mm 형식으로 다시 시도하세요" |
| 5 | `end_time`을 `start_time`보다 빠르게 | `error` + "end_time이 start_time보다 빠릅니다" |
| 6 | `channel`을 `"kakao"`로 변경 | `error` + "channel은 email 또는 sms여야 합니다" |
| 7 | JSON 중괄호 하나 지우기 | `error` + "올바른 JSON이 아닙니다" |
| 8 | `name`을 `"create_event"`로 변경 | `error` + "알 수 없는 도구" + 사용 가능한 도구 목록 |

### 테스트 진행 현황 (2026-06-05, Pixel_8_API_36 에뮬레이터)

| 테스트 | 결과 | 비고 |
|---|---|---|
| 문자 예시 (#3) | ✅ 통과 | 메시지 앱에 번호+초안 채워짐, 전송은 사용자 몫인 것까지 확인 |
| 캘린더 예시 (#1) | 🔶 부분 확인 | Intent가 구글 캘린더에 정상 전달되는 것까지 시스템 로그로 검증. 에뮬레이터에 구글 계정이 없어 로그인 화면에서 중단 — **로그인 후 재테스트 필요** |
| 메일 예시 (#2) | ⏸ 미실행 | Gmail도 구글 계정 필요 — **로그인 후 테스트 필요** |
| 에러 케이스 (#4~8) | ⏸ 미실행 | 에뮬레이터에서 JSON 수정해가며 확인 필요 |

> 진행하면서 이 표를 갱신해주세요. 실기기에서 테스트하면 더 확실합니다 (진짜 캘린더/메일 앱 + 계정이 이미 있으므로).

## 핵심 개념: 도구(Tool)가 뭔가요?

LLM에게 "이런 기능을 쓸 수 있어"라고 알려주는 **함수 명세 + 실제 실행 코드** 묶음입니다.

### 1) LLM에게 알려주는 부분 — declaration

각 도구는 자신의 사용법을 JSON Schema로 선언합니다. 이게 시스템 프롬프트에 들어갑니다:

```json
{
  "name": "open_compose",
  "description": "메일 또는 문자(SMS) 작성 화면을 초안이 채워진 상태로 엽니다. ...",
  "parameters": {
    "type": "object",
    "properties": {
      "channel": { "type": "string", "enum": ["email", "sms"], "description": "..." },
      "to":      { "type": "string", "description": "..." },
      "body":    { "type": "string", "description": "..." }
    },
    "required": ["channel", "to", "body"]
  }
}
```

> ⚠️ `description`을 대충 쓰면 안 됩니다. **LLM은 이 description만 보고 도구를 언제/어떻게 쓸지 판단**합니다.
> 특히 우리는 Gemma 같은 소형 모델을 쓰기 때문에, 날짜 형식 예시(`2026-06-10T14:00`)처럼
> 구체적인 힌트를 description에 넣어줘야 실수가 줄어듭니다.

### 2) LLM이 도구를 호출하는 형식 — tool call

LLM이 도구를 쓰기로 결정하면 이런 JSON을 출력합니다:

```json
{
  "name": "create_calendar_event",
  "args": {
    "title": "김민준 부장 미팅",
    "start_time": "2026-06-10T14:00"
  }
}
```

이걸 `ToolRegistry.dispatch(...)`에 넘기면 알아서 해당 도구를 찾아 실행합니다.

### 3) 도구가 LLM에게 돌려주는 형식 — 결과 JSON

성공 시:

```json
{ "status": "success", "message": "캘린더 일정 등록 화면을 열었습니다. ..." }
```

실패 시:

```json
{ "status": "error", "message": "start_time 형식이 올바르지 않습니다. yyyy-MM-ddTHH:mm 형식으로 다시 시도하세요." }
```

**중요한 규칙 2가지:**

- **실패해도 예외(Exception)를 던지지 말고 `error` JSON으로 반환하세요.**
  에러 메시지가 LLM에게 전달되면, LLM이 스스로 형식을 고쳐 재시도하거나
  `ask_clarification`으로 사용자에게 되물을 수 있습니다. 예외를 던지면 에이전트 루프가 끊깁니다.
- **결과 메시지에 사실만 쓰세요.** 예를 들어 캘린더 도구는 "등록했습니다"가 아니라
  "등록 **화면을 열었습니다**"라고 반환합니다. 실제 저장은 사용자가 하는 거라서,
  "등록했습니다"라고 하면 LLM이 사용자에게 "일정 등록 완료!"라고 거짓 보고하게 됩니다.

## 새 도구 만드는 방법 (팀원용 가이드)

`search_contacts_keyword`, `update_contact` 등 자기 담당 도구를 만들 때 이대로 따라하세요.

### Step 1. `agent/tools/` 폴더에 클래스 파일 생성

`AgentTool` 인터페이스를 구현합니다. 채워야 할 것은 딱 3개입니다:

```kotlin
package com.example.hjp.agent.tools

import org.json.JSONObject

class GetCurrentDatetimeTool : AgentTool {

    // 1. 도구 이름 — LLM이 이 이름으로 호출함
    override val name = "get_current_datetime"

    // 2. LLM에게 줄 사용 설명서 (JSON Schema)
    override val declaration = JSONObject(
        """
        {
          "name": "get_current_datetime",
          "description": "현재 날짜와 시각을 조회합니다. '내일', '다음주' 같은 상대 날짜를 계산하기 전에 먼저 호출하세요.",
          "parameters": { "type": "object", "properties": {} }
        }
        """
    )

    // 3. 실제 실행 로직 — args로 받은 인자를 처리하고 결과를 문자열로 반환
    override suspend fun execute(args: JSONObject): String {
        val now = java.text.SimpleDateFormat(
            "yyyy-MM-dd'T'HH:mm (EEEE)", java.util.Locale.KOREAN
        ).format(java.util.Date())
        return ToolResults.success("현재 시각: $now")
    }
}
```

> 💡 `suspend fun`이 뭔가요?: 코틀린의 비동기 함수 표시입니다. DB 조회처럼 시간이 걸리는
> 작업을 UI를 멈추지 않고 처리하기 위한 것으로, 일단 일반 함수처럼 작성하면 됩니다.
> DB 접근(Room)이 필요해지면 그때 자연스럽게 활용됩니다.

### Step 2. `ToolRegistry`에 등록

현재 `MainActivity.kt`의 registry 생성 부분에 한 줄 추가:

```kotlin
val registry = ToolRegistry(
    CreateCalendarEventTool(applicationContext),
    OpenComposeTool(applicationContext),
    GetCurrentDatetimeTool(),          // ← 추가
)
```

### Step 3. 테스트 화면에서 검증

앱을 실행하고 입력창에 tool call JSON을 직접 써서 실행해 봅니다:

```json
{ "name": "get_current_datetime", "args": {} }
```

정상 케이스뿐 아니라 **에러 케이스도 꼭 테스트**하세요 (필수 인자 빼먹기, 형식 틀리기 등).
에러일 때 LLM이 보고 고칠 수 있을 만큼 친절한 메시지가 나오는지 확인하면 됩니다.

## 구현된 도구 상세

### create_calendar_event — 캘린더 일정 등록

| 인자 | 필수 | 설명 |
|---|---|---|
| `title` | ✅ 필수 | 일정 제목 |
| `start_time` | ✅ 필수 | `yyyy-MM-ddTHH:mm` 형식 (예: `2026-06-10T14:00`) |
| `end_time` | 선택 | 생략 시 시작 1시간 후 |
| `location` | 선택 | 장소 |
| `description` | 선택 | 메모 (명함 정보를 넣으면 좋음) |
| `attendee_emails` | 선택 | 참석자 이메일 배열 |

**동작 방식**: 안드로이드의 **Intent**(앱끼리 작업을 요청하는 메시지 시스템)로
캘린더 앱의 "일정 등록 화면"을 엽니다. 내용은 미리 채워지고 **저장 버튼은 사용자가 누릅니다**.

캘린더 DB에 직접 쓰는 방법(CalendarProvider)도 있지만 일부러 안 썼습니다:
- 직접 쓰기는 `WRITE_CALENDAR` 권한 요청 팝업이 필요함
- LLM이 날짜를 잘못 해석해도 그대로 저장돼 버림 (Intent 방식은 사용자가 저장 전에 확인 가능)

### open_compose — 메일/문자 작성 화면 열기

| 인자 | 필수 | 설명 |
|---|---|---|
| `channel` | ✅ 필수 | `"email"` 또는 `"sms"` |
| `to` | ✅ 필수 | email이면 메일 주소, sms면 전화번호 |
| `subject` | 선택 | 메일 제목 (email 전용) |
| `body` | ✅ 필수 | 초안 본문 — **LLM이 직접 작성해서 넘김** |

**동작 방식**: `mailto:` / `smsto:` Intent로 메일/문자 앱의 작성 화면을 열고 초안을 채웁니다.
**전송 버튼은 사용자가 누릅니다.**

이 도구는 "초안을 작성하는" 도구가 아니라 "**작성된 초안을 받아 화면을 여는**" 도구입니다.
메일 문구 생성은 LLM의 역할이고, 그 결과물이 `body` 인자로 들어옵니다.

## 자주 묻는 질문

**Q. 도구를 실행했는데 "앱이 설치되어 있지 않습니다" 에러가 떠요.**
에뮬레이터에 캘린더/메일 앱이 없어서 그렇습니다. Google Play 지원 에뮬레이터 이미지를 쓰거나
실제 기기로 테스트하세요. (이 에러 자체는 도구가 의도대로 동작한 것이고, 실제 서비스에서도
이 메시지가 LLM에게 전달되어 사용자에게 상황을 설명하게 됩니다.)

**Q. `AndroidManifest.xml`의 `<queries>`는 뭔가요?**
Android 11부터는 보안상 다른 앱의 존재를 함부로 조회할 수 없습니다.
"우리 앱은 캘린더/메일/문자 앱을 찾아야 한다"고 미리 선언하는 부분입니다. 건드리지 않아도 됩니다.

**Q. 빌드가 안 돼요.**
- `File > Sync Project with Gradle Files` 먼저 시도
- 그래도 안 되면 `Build > Clean Project` 후 다시 빌드
- import 에러(빨간 줄)가 떠도 실제 빌드는 통과하는 경우가 있습니다 (IDE 인덱싱 지연)

**Q. 도구 이름이나 인자 이름을 바꾸고 싶어요.**
바꿔도 되지만, **declaration의 이름과 execute에서 읽는 이름이 반드시 일치**해야 하고,
시스템 프롬프트/다른 도구 description에서 그 이름을 언급하고 있다면 같이 바꿔야 합니다.
바꾸기 전에 팀에 공유하세요.
