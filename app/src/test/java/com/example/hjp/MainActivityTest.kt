package com.example.hjp

import com.example.hjp.data.BusinessCardEntity
import com.example.hjp.search.CardSearchHit
import com.example.hjp.search.CardSearchResponse
import com.example.hjp.search.FieldFilters
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 스트레스 테스트로 찾은 결정적 우회/거절감지 로직이 파이썬 확인용 구현과 같은 판정을
 * 내는지 본다. 기대값은 hybrid_server.py 로 실측한 결과와 동일하다.
 */
class MainActivityTest {

    // ---- 자기참조 질문 -----------------------------------------------------

    @Test
    fun `자기참조 질문을 감지한다`() {
        listOf("너는 누구야?", "너 뭐야", "당신은 누구세요?", "너 몇 살이야?", "너는 AI야?")
            .forEach { assertTrue("'$it' 가 자기참조로 안 잡힘", isSelfReferenceQuestion(it)) }
    }

    @Test
    fun `명함 검색 질문은 자기참조가 아니다`() {
        listOf("안정우씨 어디서 만났더라", "판교에 있는 디자이너 알려줘", "김철수 전화번호 알려줘")
            .forEach { assertFalse("'$it' 가 자기참조로 오판됨", isSelfReferenceQuestion(it)) }
    }

    @Test
    fun `빈 질문은 자기참조가 아니다`() {
        assertFalse(isSelfReferenceQuestion(""))
        assertFalse(isSelfReferenceQuestion("   "))
    }

    // ---- 전체 개수 질문 -----------------------------------------------------

    @Test
    fun `조건 없는 전체 질문을 감지한다`() {
        listOf("전체 명함이 몇 장이야?", "이름 목록 다 보여줘", "명함 전부 알려줘", "모두 보여줘")
            .forEach { assertTrue("'$it' 가 전체질문으로 안 잡힘", isUnfilteredListAllQuestion(it)) }
    }

    @Test
    fun `직급 이름이 전체와 겹쳐도 오탐하지 않는다`() {
        // "전부"/"몇" 등이 들어 있어도 구체적 조건(직급)이 남으면 전체질문이 아니다.
        listOf(
            "과장 전부 알려줘", "부장 목록 보여줘", "디자이너 전부 알려줘",
            "판교에서 일하는 사람 몇명이지?", "판교에 총 몇명이야?",
        ).forEach { assertFalse("'$it' 가 전체질문으로 오판됨", isUnfilteredListAllQuestion(it)) }
    }

    @Test
    fun `전체 모두 없이도 총과 몇이 같이 있으면 전체질문으로 본다`() {
        // "전체 명함이 몇 장이야?" 류 우회가 이 문구는 못 타서 "총 5명"으로 잘못 답했었다
        // (top-5를 전체로 착각). "총"+"몇" 신호를 추가해서 잡는다(회귀 재발 방지).
        listOf("등록된 사람 총 몇 명이야?", "총 몇 명이야?", "등록된 명함 총 몇 개야?")
            .forEach { assertTrue("'$it' 가 전체질문으로 안 잡힘", isUnfilteredListAllQuestion(it)) }
    }

    // ---- 조건 있는 카운트 질문 ------------------------------------------------

    @Test
    fun `조건 있는 카운트 질문을 감지한다`() {
        listOf("판교에 몇 명 있어?", "이사 직급 몇 명이야?", "AI 개발하는 사람 몇 명이야?")
            .forEach { assertTrue("'$it' 가 조건카운트로 안 잡힘", isFilteredCountQuestion(it)) }
    }

    @Test
    fun `조건 없는 전체질문은 조건카운트가 아니다`() {
        // 이쪽은 총원수 우회(isUnfilteredListAllQuestion)가 먼저 처리해야 한다.
        listOf("등록된 사람 총 몇 명이야?", "전체 명함이 몇 장이야?")
            .forEach { assertFalse("'$it' 가 조건카운트로 오판됨", isFilteredCountQuestion(it)) }
    }

    @Test
    fun `개수를 안 묻는 질문은 조건카운트가 아니다`() {
        listOf("안정우 전화번호 뭐야?", "판교에 있는 디자이너 알려줘", "")
            .forEach { assertFalse("'$it' 가 조건카운트로 오판됨", isFilteredCountQuestion(it)) }
    }

    @Test
    fun `전체 신호 단어가 아예 없으면 전체질문이 아니다`() {
        assertFalse(isUnfilteredListAllQuestion("안정우씨 어디서 만났더라"))
        assertFalse(isUnfilteredListAllQuestion(""))
    }

    // ---- 거절 문구 감지 확장(REJECTION_MARKERS) ------------------------------

    @Test
    fun `고정 문구 외의 거절 말투도 감지한다`() {
        assertTrue(REJECTION_MARKERS.any { it in "김철수 전화번호는 찾지 못했습니다." })
        assertTrue(REJECTION_MARKERS.any { it in "해당 조건을 찾을 수 없습니다." })
    }

    @Test
    fun `필드가 없다는 정상 답변은 거절로 오인하지 않는다`() {
        // "없습니다" 단독은 REJECTION_MARKERS 에 없다 — 존재하는 사람의 빈 필드 답변까지
        // 거절로 잘못 인식하면 카드가 지워진다.
        assertFalse(REJECTION_MARKERS.any { it in "안정우는 나이가 없습니다." })
    }

    @Test
    fun `속성을 생략한 후속은 직전 턴의 속성을 이어받는다`() {
        // 실측(pass^3 3회 모두 재현): "○○씨 회사가 어디야?" 다음 "음가영씨는?" 에
        // 회사가 아니라 이름만 "음가영"으로 답했다. 검색은 맞는데 무엇을 물었는지가 빠졌다.
        assertEquals("음가영씨 회사", carryOverAttribute("음가영씨는?", "회사"))
        assertEquals("음가영 회사", carryOverAttribute("음가영은?", "회사"))
        assertEquals("하채원씨 부서", carryOverAttribute("하채원씨는?", "부서"))
    }

    @Test
    fun `속성이 이미 있거나 이어받을 게 없으면 질문을 그대로 둔다`() {
        // 속성 명사가 이미 있으면 손대지 않는다 — 반대 방향 생략은 resolveSearchQuery 담당.
        assertEquals("주소는?", carryOverAttribute("주소는?", "회사"))
        assertEquals("음가영씨 직급은?", carryOverAttribute("음가영씨 직급은?", "회사"))
        // 이어받을 속성이 없으면 그대로.
        assertEquals("음가영씨는?", carryOverAttribute("음가영씨는?", null))
        // 문장형 질문은 대상이 아니다.
        assertEquals("판교에 있는 디자이너 찾아줘", carryOverAttribute("판교에 있는 디자이너 찾아줘", "회사"))
        assertEquals("그 사람들 회사 알려줘", carryOverAttribute("그 사람들 회사 알려줘", "주소"))
    }

    @Test
    fun `그중에 로 좁히면 앞 턴 조건을 이어받는다`() {
        // 실측: "대전에 있는 사람 찾아줘" -> "그중에 변호사만" 에서 지역이 사라져
        // 전국 변호사가 나왔다. 앞 턴 조건어를 앞에 붙여 필터 추출이 합치게 한다.
        assertEquals("대전 그중에 변호사만", applyNarrowing("그중에 변호사만", "대전"))
        assertEquals("대전 변호사 그중 부장급은?", applyNarrowing("그중 부장급은?", "대전 변호사"))
    }

    @Test
    fun `좁히기 표현이 없거나 이어받을 조건이 없으면 그대로 둔다`() {
        assertEquals("변호사 찾아줘", applyNarrowing("변호사 찾아줘", "대전"))
        assertEquals("그중에 변호사만", applyNarrowing("그중에 변호사만", null))
        assertEquals("그중에 변호사만", applyNarrowing("그중에 변호사만", ""))
    }

    @Test
    fun `attributeOf 는 질문이 물어본 속성을 뽑는다`() {
        assertEquals("회사", attributeOf("음가영씨 회사가 어디야?"))
        assertEquals("부서", attributeOf("부서는?"))
        assertNull(attributeOf("판교에 있는 디자이너 찾아줘"))
    }

    @Test
    fun `narrowByAnswer 는 거절 답변이면 카드를 모두 비운다`() {
        val search = sampleSearchResponse(listOf("안정우"))
        val (narrowed, dropped) = narrowByAnswer(search, "김철수 전화번호는 찾지 못했습니다.")
        assertTrue(narrowed.results.isEmpty())
        assertEquals(listOf("안정우"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 언급된 사람만 남긴다`() {
        val search = sampleSearchResponse(listOf("안정우", "하채원"))
        val (narrowed, dropped) = narrowByAnswer(search, "안정우의 회사는 그레이스패션입니다.")
        assertEquals(listOf("안정우"), narrowed.results.map { it.card.name })
        assertEquals(listOf("하채원"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 이름으로 특정된 한 사람은 짧은 답변에도 남긴다`() {
        // 실측 회귀(멀티턴): "손다은씨 회사가 어디야?" 로 한 사람이 특정된 뒤
        // "직급은?" -> "AI 개발자", "부서는?" -> "데이터사이언스팀" 처럼 필드 값만
        // 짧게 답하면 이름·회사·주소가 답변에 없어서 카드가 통째로 사라졌다.
        // 후보가 한 명이면 '누구를 가리키는지' 고를 게 없으므로 그대로 둔다.
        val search = sampleSearchResponse(listOf("안정우"))
            .copy(fieldFilters = FieldFilters(names = listOf("안정우")))
        for (answer in listOf("AI 개발자", "데이터사이언스팀", "기술교류회에서 만났습니다.")) {
            val (narrowed, dropped) = narrowByAnswer(search, answer)
            assertEquals("답변='$answer'", listOf("안정우"), narrowed.results.map { it.card.name })
            assertTrue(dropped.isEmpty())
        }
    }

    @Test
    fun `narrowByAnswer 는 이름 조건이 있어도 후보가 여럿이면 무관한 답변에 카드를 비운다`() {
        // 위 예외는 후보가 하나일 때만이다 — 동명이인 2명 중 누구인지 답변이
        // 안 가리키면 예전대로 비운다(무관한 명함이 남는 걸 막는 게 이 단계의 목적).
        val search = sampleSearchResponse(listOf("하채원", "하채원"))
            .copy(fieldFilters = FieldFilters(names = listOf("하채원")))
        val (narrowed, dropped) = narrowByAnswer(search, "오늘은 화요일입니다.")
        assertTrue(narrowed.results.isEmpty())
        assertEquals(2, dropped.size)
    }

    @Test
    fun `narrowByAnswer 는 이름 조건 없이 한 명이면 무관한 답변에 카드를 비운다`() {
        // 지역·직함으로만 좁혀져 우연히 1명이 남은 경우까지 살려두면
        // "오늘 날씨 어때?" 에 엉뚱한 명함이 뜬다.
        val search = sampleSearchResponse(listOf("안정우"))
        val (narrowed, _) = narrowByAnswer(search, "오늘은 화요일입니다.")
        assertTrue(narrowed.results.isEmpty())
    }

    @Test
    fun `narrowByAnswer 는 총 N명 집계형 답변이면 원본을 유지한다`() {
        // 이름을 안 대는 게 이 형식의 정상 동작이다(프롬프트 규칙 3번) — 카드까지
        // 비우면 안 된다.
        val search = sampleSearchResponse(listOf("정철수", "음수진", "김민재"))
        val (narrowed, dropped) = narrowByAnswer(search, "총 3명")
        assertEquals(listOf("정철수", "음수진", "김민재"), narrowed.results.map { it.card.name })
        assertTrue(dropped.isEmpty())
    }

    @Test
    fun `narrowByAnswer 는 이름 없이 회사명으로만 답해도 카드를 남긴다`() {
        // 회귀 방지: "문선영씨 회사가 어디야?" -> "주식회사 노블어패럴입니다." 처럼
        // 필드 값만 답하는 게 정상인 질문이 많은데, 이름이 없다고 카드를 지워버렸었다.
        val search = sampleSearchResponse(listOf("문선영", "차우주"))
        val (narrowed, dropped) = narrowByAnswer(search, "주식회사 노블어패럴0입니다.")
        assertEquals(listOf("문선영"), narrowed.results.map { it.card.name })
        assertEquals(listOf("차우주"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 전화 뒷자리로만 답해도 카드를 남긴다`() {
        // "전화번호 뒤 4자리" -> "2069" 같은 답변(이름도 필드명도 없음).
        val search = sampleSearchResponse(listOf("문선영"))
        val (narrowed, _) = narrowByAnswer(search, "2000")
        assertEquals(listOf("문선영"), narrowed.results.map { it.card.name })
    }

    @Test
    fun `narrowByAnswer 는 주소로만 답해도 카드를 남긴다`() {
        val search = sampleSearchResponse(listOf("문선영"))
        val (narrowed, _) = narrowByAnswer(search, "서울특별시 반포대로 0")
        assertEquals(listOf("문선영"), narrowed.results.map { it.card.name })
    }

    @Test
    fun `narrowByAnswer 는 LLM이 주소 괄호를 생략해도 카드를 남긴다`() {
        // 실측: 카드가 "강원도 당진시 반포대2로 67 (승현이김리)" 인데 LLM 은 괄호를 뺀
        // "강원도 당진시 반포대2로 67" 로 답해서 값이 안 맞아 카드가 지워졌다.
        val card = BusinessCardEntity(
            "a1", "문선영", "", "주식회사 노블어패럴", "직급", "부서", "산업", "지역",
            "010-9322-2069", "m@corp.kr", "강원도 당진시 반포대2로 67 (승현이김리)", "", "", 0L,
        )
        val search = CardSearchResponse(
            query = "q", engine = "test", retrieval = "keyword",
            keywordQuery = "q", semanticQuery = "q",
            results = listOf(CardSearchHit(card, 1.0, 0, null, 0f)),
        )
        val (narrowed, _) = narrowByAnswer(search, "강원도 당진시 반포대2로 67")
        assertEquals(listOf("문선영"), narrowed.results.map { it.card.name })
    }

    @Test
    fun `narrowByAnswer 는 집계 수가 후보보다 적으면 그 수만큼만 남긴다`() {
        // 실측: "AI 개발하는 사람 찾아줘" -> '총 2명' 인데 카드 5장이 떴다.
        // 정렬이 정확 일치를 앞에 두므로 상위 N개가 그 N명이다.
        val search = sampleSearchResponse(listOf("어은지", "황보미영", "선지아", "차우주", "문선영"))
        val (narrowed, dropped) = narrowByAnswer(search, "총 2명")
        assertEquals(listOf("어은지", "황보미영"), narrowed.results.map { it.card.name })
        assertEquals(listOf("선지아", "차우주", "문선영"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 집계 수가 후보와 같거나 크면 그대로 둔다`() {
        val search = sampleSearchResponse(listOf("가", "나", "다"))
        assertEquals(3, narrowByAnswer(search, "총 3명").first.results.size)
        assertEquals(3, narrowByAnswer(search, "총 9명").first.results.size)
    }

    @Test
    fun `narrowByAnswer 는 총 0명이면 카드를 비운다`() {
        // "총 0명"은 숫자로 표현된 거절이다. 집계형이라고 카드를 살려두면
        // "총 0명"이라 답하면서 명함 5장이 뜨는 모순이 된다.
        // 실측: "울릉도 근무자"(그 지역 없음) -> 답변 '총 0명', 카드 5장.
        val search = sampleSearchResponse(listOf("지하윤", "김여름", "손선우"))
        val (narrowed, dropped) = narrowByAnswer(search, "총 0명")
        assertTrue(narrowed.results.isEmpty())
        assertEquals(listOf("지하윤", "김여름", "손선우"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 총 0명이 아닌 집계형은 그대로 둔다`() {
        // 경계값 확인 — 0 만 거절로 보고 10·20 같은 값은 정상 집계로 남긴다.
        listOf("총 10명", "총 20 명").forEach { answer ->
            val search = sampleSearchResponse(listOf("가", "나"))
            val (narrowed, dropped) = narrowByAnswer(search, answer)
            assertEquals("'$answer' 가 잘못 비워짐", 2, narrowed.results.size)
            assertTrue(dropped.isEmpty())
        }
    }

    @Test
    fun `narrowByAnswer 는 이름도 총N명 형식도 없으면 명함과 무관한 답변으로 보고 카드를 비운다`() {
        // 실측: "오늘 날씨 어때?" -> "날씨 정보는 명함 컨텍스트에 포함되어 있지 않습니다."
        // 인데 무관한 후보 카드가 그대로 남아있던 버그.
        val search = sampleSearchResponse(listOf("모정", "설우진", "이혜린"))
        val (narrowed, dropped) = narrowByAnswer(search, "날씨 정보는 명함 컨텍스트에 포함되어 있지 않습니다.")
        assertTrue(narrowed.results.isEmpty())
        assertEquals(listOf("모정", "설우진", "이혜린"), dropped)
    }

    @Test
    fun `narrowByAnswer 는 존재하지 않는 이름에 대한 의도 확인 답변에도 카드를 비운다`() {
        // 실측: "홍길동 명함 삭제해 줘"(존재 안 하는 이름) -> "홍길동 명함 삭제를
        // 요청하셨습니다." 인데 엉뚱한 홍씨 후보 카드가 그대로 남아있던 버그. "홍길동"이
        // 답변에 등장하지만 후보 목록엔 없으니 mentioned 는 여전히 비어 있다.
        val search = sampleSearchResponse(listOf("홍지우", "홍정민"))
        val (narrowed, dropped) = narrowByAnswer(search, "홍길동 명함 삭제를 요청하셨습니다.")
        assertTrue(narrowed.results.isEmpty())
        assertEquals(listOf("홍지우", "홍정민"), dropped)
    }

    /**
     * 각 카드에 서로 다른 회사/주소/전화를 준다 — 필드 기반 매칭을 검증할 수 있게.
     * 회사·주소는 이름을 포함하지 않는다(이름 매칭과 필드 매칭을 분리해서 보려고).
     */
    private fun sampleSearchResponse(names: List<String>): CardSearchResponse {
        val hits = names.mapIndexed { i, name ->
            CardSearchHit(
                card = BusinessCardEntity(
                    "id$i", name, "", "주식회사 노블어패럴$i", "직급", "부서",
                    "산업", "지역", "010-1000-200$i", "$name@corp.co.kr",
                    "서울특별시 반포대로 $i", "", "", 0L,
                ),
                score = 1.0,
                keywordRank = i,
                vectorRank = null,
                similarity = 0f,
            )
        }
        return CardSearchResponse(
            query = "q", engine = "test", retrieval = "keyword",
            keywordQuery = "q", semanticQuery = "q", results = hits,
        )
    }
}
