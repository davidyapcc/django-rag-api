from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "owner", "status", "chunk_count", "created_at"]
    list_filter = ["status"]
    search_fields = ["title"]
