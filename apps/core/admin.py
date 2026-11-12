from django.contrib import admin

from .models import DailySpend, OwnerDailySpend

admin.site.register(DailySpend)
admin.site.register(OwnerDailySpend)
