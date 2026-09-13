from django.contrib import admin

from accounts.models import Address, User


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = ("region", "district_or_city", "street", "house_number", "house_number_sub", "label")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "external_id", "created_at")
    list_filter = ("channel",)
    search_fields = ("external_id",)
    inlines = [AddressInline]


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "region", "district_or_city", "street",
        "house_number", "house_number_sub", "label", "created_at",
    )
    list_filter = ("region",)
    search_fields = ("street", "district_or_city", "label")
    autocomplete_fields = ("user",)
