package com.example.hjp.data;

import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Transaction;

import java.util.List;

@Dao
public abstract class BusinessCardDao {
    @Query("SELECT COUNT(*) FROM business_cards")
    public abstract int countCards();

    @Query("SELECT * FROM business_cards ORDER BY name")
    public abstract List<BusinessCardEntity> allCards();

    @Query("SELECT * FROM business_cards WHERE id = :id LIMIT 1")
    public abstract BusinessCardEntity findCard(String id);

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract void upsertCard(BusinessCardEntity card);

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract void upsertFts(BusinessCardFtsEntity fts);

    @Query("DELETE FROM business_cards_fts")
    public abstract void clearFts();

    @Transaction
    public void upsertCards(List<BusinessCardEntity> cards) {
        int row = 1;
        for (BusinessCardEntity card : cards) {
            upsertCard(card);
            upsertFts(new BusinessCardFtsEntity(row++, card.id, card.searchableText()));
        }
    }

    @Query("SELECT card_id FROM business_cards_fts WHERE business_cards_fts MATCH :matchQuery LIMIT :limit")
    public abstract List<String> searchFtsIds(String matchQuery, int limit);

    @Query("SELECT id FROM business_cards WHERE "
            + "name LIKE :like OR nameEn LIKE :like OR company LIKE :like OR title LIKE :like "
            + "OR department LIKE :like OR industry LIKE :like OR location LIKE :like "
            + "OR memo LIKE :like OR tags LIKE :like LIMIT :limit")
    public abstract List<String> searchLikeIds(String like, int limit);

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    public abstract void upsertEmbedding(CardEmbeddingEntity embedding);

    @Query("SELECT * FROM card_embeddings WHERE cardId = :cardId AND modelName = :modelName AND sourceHash = :sourceHash LIMIT 1")
    public abstract CardEmbeddingEntity findEmbedding(String cardId, String modelName, String sourceHash);

    @Query("SELECT * FROM card_embeddings WHERE modelName = :modelName")
    public abstract List<CardEmbeddingEntity> embeddingsForModel(String modelName);
}
