from django.contrib import admin
from .models import Page, Section


class SectionInline(admin.TabularInline):
    model = Section
    extra = 1


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("brand", "slug", "title", "is_published")
    list_filter = ("brand", "is_published")
    search_fields = ("slug", "title")
    inlines = [SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("page", "type", "order", "is_active")
    list_filter = ("type", "is_active", "page__brand")
    ordering = ("page", "order")