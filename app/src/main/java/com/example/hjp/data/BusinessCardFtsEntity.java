package com.example.hjp.data;

import androidx.room.ColumnInfo;
import androidx.room.Entity;
import androidx.room.Fts4;
import androidx.room.PrimaryKey;

@Fts4
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
