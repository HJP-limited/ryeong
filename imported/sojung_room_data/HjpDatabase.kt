package com.example.hjp.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [BusinessCardEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class HjpDatabase : RoomDatabase() {
    abstract fun businessCardDao(): BusinessCardDao

    companion object {
        @Volatile
        private var instance: HjpDatabase? = null

        fun getInstance(context: Context): HjpDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    HjpDatabase::class.java,
                    "hjp.db",
                ).build().also { instance = it }
            }
    }
}
