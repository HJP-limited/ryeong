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
        version = 1,
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
                ).build();
                instance = current;
            }
            return current;
        }
    }
}
