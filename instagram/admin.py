from django.contrib import admin
from .models import InstagramAccount


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'username', 'is_active', 'token_expires_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('user__email', 'username')
