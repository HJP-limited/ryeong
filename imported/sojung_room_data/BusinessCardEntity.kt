package com.example.hjp.data

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "business_cards")
data class BusinessCardEntity(
    @PrimaryKey val id: String,
    val name: String?,
    val company: String?,
    val department: String?,
    val title: String?,
    val phone: String?,
    val mobile: String?,
    val email: String?,
    val address: String?,
    val website: String?,
    val memo: String?,
    @ColumnInfo(name = "updated_at") val updatedAt: String?,
)

fun BusinessCardEntity.toDomain(): BusinessCard =
    BusinessCard(
        id = id,
        name = name,
        company = company,
        department = department,
        title = title,
        phone = phone,
        mobile = mobile,
        email = email,
        address = address,
        website = website,
        memo = memo,
        updatedAt = updatedAt,
    )

fun BusinessCard.toEntity(): BusinessCardEntity =
    BusinessCardEntity(
        id = id,
        name = name,
        company = company,
        department = department,
        title = title,
        phone = phone,
        mobile = mobile,
        email = email,
        address = address,
        website = website,
        memo = memo,
        updatedAt = updatedAt,
    )
