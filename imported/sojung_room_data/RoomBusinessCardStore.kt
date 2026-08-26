package com.example.hjp.data

class RoomBusinessCardStore(
    private val dao: BusinessCardDao,
) : BusinessCardStore {

    override suspend fun findById(id: String): BusinessCard? {
        seedIfEmpty()
        return dao.findById(id)?.toDomain()
    }

    override suspend fun update(
        id: String,
        updates: Map<String, String>,
        clearFields: Set<String>,
        updatedAt: String,
    ): BusinessCardUpdateResult? {
        seedIfEmpty()
        val before = dao.findById(id)?.toDomain() ?: return null
        val after = before.copy(
            name = resolveField("name", before.name, updates, clearFields),
            company = resolveField("company", before.company, updates, clearFields),
            department = resolveField("department", before.department, updates, clearFields),
            title = resolveField("title", before.title, updates, clearFields),
            phone = resolveField("phone", before.phone, updates, clearFields),
            mobile = resolveField("mobile", before.mobile, updates, clearFields),
            email = resolveField("email", before.email, updates, clearFields),
            address = resolveField("address", before.address, updates, clearFields),
            website = resolveField("website", before.website, updates, clearFields),
            memo = resolveField("memo", before.memo, updates, clearFields),
            updatedAt = updatedAt,
        )
        dao.update(after.toEntity())
        return BusinessCardUpdateResult(before = before, after = after)
    }

    private suspend fun seedIfEmpty() {
        if (dao.count() > 0) return
        dao.insertAll(SAMPLE_CARDS.map { it.toEntity() })
    }

    private fun resolveField(
        field: String,
        currentValue: String?,
        updates: Map<String, String>,
        clearFields: Set<String>,
    ): String? =
        when {
            field in updates -> updates.getValue(field)
            field in clearFields -> null
            else -> currentValue
        }

    companion object {
        val SAMPLE_CARDS = listOf(
            BusinessCard(
                id = "sample-card-1",
                name = "Kim Minjun",
                company = "ABC Electronics",
                department = "Sales",
                title = "Manager",
                phone = "02-1111-2222",
                mobile = "010-1234-5678",
                email = "minjun.kim@example.com",
                address = "Gangnam-gu, Seoul",
                website = "https://abc.example.com",
                memo = "Met at AI Expo. Interested in OCR pipeline.",
            ),
            BusinessCard(
                id = "sample-card-2",
                name = "Lee Seoha",
                company = "Bluefin Labs",
                department = "Product",
                title = "Product Lead",
                phone = "02-2222-3333",
                mobile = "010-2345-6789",
                email = "seoha.lee@bluefin.example.com",
                address = "Pangyo, Seongnam",
                website = "https://bluefin.example.com",
                memo = "Asked for a follow-up demo next week.",
            ),
            BusinessCard(
                id = "sample-card-3",
                name = "Park Jihoon",
                company = "Northstar Ventures",
                department = "Investment",
                title = "Partner",
                phone = "02-3333-4444",
                mobile = "010-3456-7890",
                email = "jihoon.park@northstar.example.com",
                address = "Yeouido, Seoul",
                website = "https://northstar.example.com",
                memo = "Potential investor contact.",
            ),
            BusinessCard(
                id = "sample-card-4",
                name = "Choi Yuna",
                company = "Hanbit Medical",
                department = "R&D",
                title = "Research Director",
                phone = "031-444-5555",
                mobile = "010-4567-8901",
                email = "yuna.choi@hanbit.example.com",
                address = "Suwon, Gyeonggi-do",
                website = "https://hanbit.example.com",
                memo = "Interested in on-device privacy guarantees.",
            ),
            BusinessCard(
                id = "sample-card-5",
                name = "Jung Haein",
                company = "Orbit Design Studio",
                department = "Brand",
                title = "Creative Director",
                phone = "02-5555-6666",
                mobile = "010-5678-9012",
                email = "haein.jung@orbit.example.com",
                address = "Seongsu-dong, Seoul",
                website = "https://orbit.example.com",
                memo = "Requested a mail draft about collaboration.",
            ),
        )
    }
}
