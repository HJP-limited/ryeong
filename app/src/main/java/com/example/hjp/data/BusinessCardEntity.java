package com.example.hjp.data;

import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;

@Entity(tableName = "business_cards")
public class BusinessCardEntity {
    @PrimaryKey
    @NonNull
    public String id;
    public String name;
    public String nameEn;
    public String company;
    public String title;
    public String department;
    public String industry;
    public String location;
    public String phone;
    public String email;
    public String address;
    public String memo;
    public String tags;
    public long updatedAtMillis;

    public BusinessCardEntity(
            @NonNull String id,
            String name,
            String nameEn,
            String company,
            String title,
            String department,
            String industry,
            String location,
            String phone,
            String email,
            String address,
            String memo,
            String tags,
            long updatedAtMillis
    ) {
        this.id = id;
        this.name = value(name);
        this.nameEn = value(nameEn);
        this.company = value(company);
        this.title = value(title);
        this.department = value(department);
        this.industry = value(industry);
        this.location = value(location);
        this.phone = value(phone);
        this.email = value(email);
        this.address = value(address);
        this.memo = value(memo);
        this.tags = value(tags);
        this.updatedAtMillis = updatedAtMillis;
    }

    public String searchableText() {
        return (name + " " + nameEn + " " + company + " " + title + " " + department + " "
                + industry + " " + location + " " + memo + " " + tags).toLowerCase();
    }

    public String ragContext() {
        return "cardId: " + id + "\n"
                + "name: " + name + "\n"
                + "company: " + company + "\n"
                + "title: " + title + "\n"
                + "department: " + department + "\n"
                + "industry: " + industry + "\n"
                + "location: " + location + "\n"
                + "memo: " + memo + "\n"
                + "tags: " + tags;
    }

    private static String value(String raw) {
        return raw == null ? "" : raw;
    }
}
