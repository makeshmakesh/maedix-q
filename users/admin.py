from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser, UserProfile, UserStats, ProfileLink, EmailOTP, ProfilePageView, ProfileLinkClick


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


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ['email', 'created_at']
    search_fields = ['email']


@admin.register(ProfilePageView)
class ProfilePageViewAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_hash', 'referrer', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['user__email', 'user__username']


@admin.register(ProfileLinkClick)
class ProfileLinkClickAdmin(admin.ModelAdmin):
    list_display = ['link', 'ip_hash', 'referrer', 'clicked_at']
    list_filter = ['clicked_at']
    search_fields = ['link__title', 'link__user__username']
