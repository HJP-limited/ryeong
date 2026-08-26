package com.example.hjp.agent.tools

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import org.json.JSONObject

/**
 * 메일/문자 작성 화면을 초안이 채워진 상태로 여는 도구.
 *
 * 초안 본문은 LLM이 명함 정보를 바탕으로 직접 생성해서 body 인자로 전달한다.
 * (이 도구는 "초안 작성"이 아니라 "초안을 받아 작성 화면을 여는" 역할)
 * 전송은 사용자가 메일/문자 앱에서 직접 한다.
 */
class OpenComposeTool(private val context: Context) : AgentTool {

    override val name = "open_compose"

    override val declaration = JSONObject(
        """
        {
          "name": "open_compose",
          "description": "메일 또는 문자(SMS) 작성 화면을 초안이 채워진 상태로 엽니다. 전송은 사용자가 직접 합니다. 본문(body)은 사용자의 요청과 명함 정보를 바탕으로 당신이 직접 작성해서 전달하세요. 받는 사람의 연락처는 명함 검색 도구로 먼저 확인하세요.",
          "parameters": {
            "type": "object",
            "properties": {
              "channel": {
                "type": "string",
                "enum": ["email", "sms"],
                "description": "email: 메일 앱, sms: 문자 앱"
              },
              "to": {
                "type": "string",
                "description": "channel이 email이면 이메일 주소, sms면 전화번호"
              },
              "subject": {
                "type": "string",
                "description": "메일 제목 (email 전용, sms에서는 무시됨)"
              },
              "body": {
                "type": "string",
                "description": "작성해 둔 초안 본문 전체"
              }
            },
            "required": ["channel", "to", "body"]
          }
        }
        """
    )

    override suspend fun execute(args: JSONObject): String {
        val to = args.optString("to")
        if (to.isBlank()) return ToolResults.error("to(받는 사람)는 필수입니다.")
        val body = args.optString("body")

        val intent = when (val channel = args.optString("channel")) {
            "email" -> buildEmailIntent(to, args.optString("subject"), body)
            "sms" -> buildSmsIntent(to, body)
            else -> return ToolResults.error("channel은 email 또는 sms여야 합니다. (받은 값: '$channel')")
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        return try {
            context.startActivity(intent)
            ToolResults.success("작성 화면을 열고 초안을 채웠습니다. 내용 확인과 전송은 사용자가 직접 합니다.")
        } catch (e: ActivityNotFoundException) {
            ToolResults.error("해당 작업을 처리할 앱(메일/문자 앱)이 설치되어 있지 않습니다.")
        }
    }

    private fun buildEmailIntent(to: String, subject: String, body: String): Intent =
        Intent(Intent.ACTION_SENDTO).apply {
            // 제목/본문까지 mailto URI에 인코딩 — EXTRA_SUBJECT/EXTRA_TEXT만 쓰면 무시하는 메일 앱이 있음
            data = Uri.parse(
                "mailto:${Uri.encode(to)}" +
                    "?subject=${Uri.encode(subject)}" +
                    "&body=${Uri.encode(body)}"
            )
            // mailto URI를 읽지 않고 EXTRA를 읽는 앱을 위해 둘 다 채워줌
            putExtra(Intent.EXTRA_EMAIL, arrayOf(to))
            putExtra(Intent.EXTRA_SUBJECT, subject)
            putExtra(Intent.EXTRA_TEXT, body)
        }

    private fun buildSmsIntent(to: String, body: String): Intent =
        Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${Uri.encode(to)}")).apply {
            putExtra("sms_body", body)
        }
}
