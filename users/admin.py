from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser, UserProfile, UserStats, ProfileLink


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    pass


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    pass


@admin.register(UserStats)
class UserStatsAdmin(admin.ModelAdmin):
    pass


@admin.register(ProfileLink)
class ProfileLinkAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'url', 'order', 'is_active', 'click_count']
    list_filter = ['is_active']
    search_fields = ['title', 'url', 'user__email', 'user__username']
    ordering = ['user', 'order']
