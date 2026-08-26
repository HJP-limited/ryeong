package com.example.hjp.data;

import android.content.Context;

import androidx.room.Database;
import androidx.room.Room;
import androidx.room.RoomDatabase;

@Database(
        entities = {
                BusinessCardEntity.class,
                BusinessCardFtsEntity.class,
                CardEmbeddingEntity.class
        },
        // v2: business_cards_fts 토크나이저를 unicode61+prefix로 변경(검색 품질 개선).
        // FTS 스키마 변경이라 destructiveMigration으로 처리 — 카드/임베딩은 seedIfEmpty()가
        // 번들 asset(cards_seed.json)에서 자동 재시딩하므로 데이터 유실이 아님.
        version = 2,
        exportSchema = false
)
public abstract class HjpDatabase extends RoomDatabase {
    public abstract BusinessCardDao businessCardDao();

    private static volatile HjpDatabase instance;

    public static HjpDatabase getInstance(Context context) {
        HjpDatabase current = instance;
        if (current != null) return current;
        synchronized (HjpDatabase.class) {
            current = instance;
            if (current == null) {
                current = Room.databaseBuilder(
                        context.getApplicationContext(),
                        HjpDatabase.class,
                        "hjp-agent.db"
                ).fallbackToDestructiveMigration().build();
                instance = current;
            }
            return current;
        }
    }
}
