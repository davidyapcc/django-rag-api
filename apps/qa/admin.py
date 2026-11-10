from django.contrib import admin

from .models import Query


@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    list_display = ["id", "owner", "question", "model", "cost_usd", "latency_ms", "created_at"]
    list_filter = ["provider", "model"]
    readonly_fields = [f.name for f in Query._meta.fields]
