package com.example.hjp.data

data class BusinessCard(
    val id: String,
    val name: String? = null,
    val company: String? = null,
    val department: String? = null,
    val title: String? = null,
    val phone: String? = null,
    val mobile: String? = null,
    val email: String? = null,
    val address: String? = null,
    val website: String? = null,
    val memo: String? = null,
    val updatedAt: String? = null,
)

data class BusinessCardUpdateResult(
    val before: BusinessCard,
    val after: BusinessCard,
)

interface BusinessCardStore {
    suspend fun findById(id: String): BusinessCard?

    suspend fun update(
        id: String,
        updates: Map<String, String>,
        clearFields: Set<String>,
        updatedAt: String,
    ): BusinessCardUpdateResult?
}
