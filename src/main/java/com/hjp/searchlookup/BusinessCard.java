package com.hjp.searchlookup;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

public final class BusinessCard {
    public final String id;
    public final String name;
    public final String nameEn;
    public final String company;
    public final String title;
    public final String department;
    public final String industry;
    public final String location;
    public final String phone;
    public final String email;
    public final String address;
    public final String memo;
    public final List<String> tags;

    public BusinessCard(
            String id,
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
            List<String> tags
    ) {
        this.id = value(id);
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
        this.tags = Collections.unmodifiableList(new ArrayList<>(tags == null ? Collections.emptyList() : tags));
    }

    public String searchableText() {
        return (name + " " + nameEn + " " + company + " " + title + " " + department + " "
                + industry + " " + location + " " + phone + " " + email + " " + address + " "
                + memo + " " + tagLine()).toLowerCase(Locale.KOREAN);
    }

    public String tagLine() {
        StringBuilder builder = new StringBuilder();
        for (String tag : tags) {
            if (builder.length() > 0) builder.append(' ');
            builder.append('#').append(tag);
        }
        return builder.toString();
    }

    private static String value(String raw) {
        return raw == null ? "" : raw;
    }
}
