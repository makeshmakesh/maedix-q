from django.contrib import admin
from .models import InstagramAccount


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'username', 'is_active', 'token_expires_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('user__email', 'username')
    readonly_fields = ('instagram_user_id', 'access_token', 'token_expires_at', 'instagram_data', 'created_at', 'updated_at')
