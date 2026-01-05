from django.contrib import admin
from .models import YouTubeAccount


@admin.register(YouTubeAccount)
class YouTubeAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'channel_title', 'channel_id', 'is_active', 'token_expires_at', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__email', 'channel_title', 'channel_id')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('user', 'is_active')
        }),
        ('Channel Info', {
            'fields': ('channel_id', 'channel_title')
        }),
        ('OAuth Tokens', {
            'fields': ('access_token', 'refresh_token', 'token_expires_at'),
            'classes': ('collapse',),
        }),
        ('Additional Data', {
            'fields': ('youtube_data',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
        }),
    )
