package com.example.hjp.agent.tools

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.provider.CalendarContract
import org.json.JSONObject
import java.text.ParseException
import java.text.SimpleDateFormat
import java.util.Locale

/**
 * 외부 캘린더 앱에 일정 등록 화면을 여는 도구.
 *
 * CalendarProvider에 직접 insert하지 않고 ACTION_INSERT 인텐트를 사용한다.
 * - 권한(WRITE_CALENDAR) 불필요
 * - LLM이 날짜를 잘못 해석해도 사용자가 캘린더 앱에서 저장 전에 확인/수정 가능
 */
class CreateCalendarEventTool(private val context: Context) : AgentTool {

    override val name = "create_calendar_event"

    override val declaration = JSONObject(
        """
        {
          "name": "create_calendar_event",
          "description": "기기의 캘린더 앱에 일정 등록 화면을 엽니다. 입력한 내용이 미리 채워진 상태로 열리며, 최종 저장은 사용자가 합니다. '내일', '다음주 화요일' 같은 상대 날짜는 먼저 get_current_datetime으로 현재 시각을 확인한 뒤 절대 시각으로 변환해서 전달하세요.",
          "parameters": {
            "type": "object",
            "properties": {
              "title": {
                "type": "string",
                "description": "일정 제목 (예: '김민준 부장 미팅')"
              },
              "start_time": {
                "type": "string",
                "description": "시작 시각. 반드시 yyyy-MM-ddTHH:mm 형식 (예: 2026-06-10T14:00)"
              },
              "end_time": {
                "type": "string",
                "description": "종료 시각. 같은 형식. 생략하면 시작 1시간 후로 설정됨"
              },
              "location": {
                "type": "string",
                "description": "장소 (선택)"
              },
              "description": {
                "type": "string",
                "description": "일정 메모. 관련 명함의 이름/회사/연락처를 넣으면 좋음 (선택)"
              },
              "attendee_emails": {
                "type": "array",
                "items": { "type": "string" },
                "description": "참석자 이메일 목록 (선택)"
              }
            },
            "required": ["title", "start_time"]
          }
        }
        """
    )

    override suspend fun execute(args: JSONObject): String {
        val title = args.optString("title")
        if (title.isBlank()) return ToolResults.error("title은 필수입니다.")

        // LLM이 준 시각 파싱 — 실패하면 에러를 반환해서 LLM이 형식을 고쳐 재시도하게 함
        val startMillis = parseDateTime(args.optString("start_time"))
            ?: return ToolResults.error(
                "start_time 형식이 올바르지 않습니다. yyyy-MM-ddTHH:mm 형식으로 다시 시도하세요. (예: 2026-06-10T14:00)"
            )
        val endMillis = args.optString("end_time")
            .takeIf { it.isNotBlank() }
            ?.let {
                parseDateTime(it) ?: return ToolResults.error(
                    "end_time 형식이 올바르지 않습니다. yyyy-MM-ddTHH:mm 형식으로 다시 시도하세요."
                )
            }
            ?: (startMillis + DEFAULT_DURATION_MILLIS)

        if (endMillis < startMillis) {
            return ToolResults.error("end_time이 start_time보다 빠릅니다. 시각을 확인해서 다시 시도하세요.")
        }

        val intent = Intent(Intent.ACTION_INSERT).apply {
            data = CalendarContract.Events.CONTENT_URI
            putExtra(CalendarContract.Events.TITLE, title)
            putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, startMillis)
            putExtra(CalendarContract.EXTRA_EVENT_END_TIME, endMillis)
            args.optString("location").takeIf { it.isNotBlank() }
                ?.let { putExtra(CalendarContract.Events.EVENT_LOCATION, it) }
            args.optString("description").takeIf { it.isNotBlank() }
                ?.let { putExtra(CalendarContract.Events.DESCRIPTION, it) }
            args.optJSONArray("attendee_emails")?.let { arr ->
                val emails = (0 until arr.length())
                    .joinToString(",") { arr.optString(it) }
                if (emails.isNotBlank()) putExtra(Intent.EXTRA_EMAIL, emails)
            }
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        return try {
            context.startActivity(intent)
            // "등록되었다"고 하면 LLM이 사용자에게 완료됐다고 거짓 보고하므로, 화면만 열렸음을 명시
            ToolResults.success("캘린더 일정 등록 화면을 열었습니다. 최종 저장은 사용자가 캘린더 앱에서 확인 후 진행합니다.")
        } catch (e: ActivityNotFoundException) {
            ToolResults.error("이 기기에 캘린더 앱이 설치되어 있지 않습니다.")
        }
    }

    /** "2026-06-10T14:00" 또는 "2026-06-10T14:00:00"을 기기 시간대 기준 epoch millis로 변환 */
    private fun parseDateTime(value: String?): Long? {
        if (value.isNullOrBlank()) return null
        for (pattern in DATE_PATTERNS) {
            try {
                val format = SimpleDateFormat(pattern, Locale.US).apply { isLenient = false }
                return format.parse(value)?.time
            } catch (e: ParseException) {
                // 다음 패턴 시도
            }
        }
        return null
    }

    companion object {
        private const val DEFAULT_DURATION_MILLIS = 60 * 60 * 1000L // 1시간
        private val DATE_PATTERNS = listOf(
            "yyyy-MM-dd'T'HH:mm:ss",
            "yyyy-MM-dd'T'HH:mm",
        )
    }
}
