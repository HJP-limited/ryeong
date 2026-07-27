package com.example.hjp.data;

import androidx.room.ColumnInfo;
import androidx.room.Entity;
import androidx.room.Fts4;
import androidx.room.FtsOptions;
import androidx.room.PrimaryKey;

// unicode61 + prefix 인덱스: 검색 담당 브랜치(ymj/embedding-search-android-eval)와 동일 설정.
// 오프라인 평가(scripts/eval_search.py 등)에서 기존 기본 토크나이저보다 Recall@1/MRR이
// 뚜렷이 높았음(특히 전화번호 조회) — 그 결과를 반영해 앱에도 적용.
@Fts4(tokenizer = FtsOptions.TOKENIZER_UNICODE61, prefix = {2, 3, 4})
@Entity(tableName = "business_cards_fts")
public class BusinessCardFtsEntity {
    @PrimaryKey
    @ColumnInfo(name = "rowid")
    public int rowId;

    @ColumnInfo(name = "card_id")
    public String cardId;

    @ColumnInfo(name = "searchable_text")
    public String searchableText;

    public BusinessCardFtsEntity(int rowId, String cardId, String searchableText) {
        this.rowId = rowId;
        this.cardId = cardId == null ? "" : cardId;
        this.searchableText = searchableText == null ? "" : searchableText;
    }
}
