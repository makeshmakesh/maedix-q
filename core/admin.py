from django.contrib import admin
from .models import Configuration, Plan, Subscription, Transaction, ContactMessage, Banner


@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'updated_at']
    search_fields = ['key', 'value']


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'plan_type', 'price_monthly', 'price_yearly', 'is_popular', 'is_active', 'order']
    list_filter = ['plan_type', 'is_active', 'is_popular']
    list_editable = ['order', 'is_active', 'is_popular']
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'plan_type', 'description')
        }),
        ('Pricing', {
            'fields': ('price_monthly', 'price_yearly')
        }),
        ('Features', {
            'fields': ('features',),
            'description': 'JSON format: [{"code": "video_gen", "description": "Video generation", "limit": 5}, ...]'
        }),
        ('Settings', {
            'fields': ('is_active', 'is_popular', 'order')
        }),
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'status', 'start_date', 'end_date', 'is_yearly']
    list_filter = ['status', 'is_yearly', 'plan']
    search_fields = ['user__email']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['user__email', 'razorpay_payment_id']


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'subject', 'is_read', 'created_at']
    list_filter = ['is_read']
    search_fields = ['name', 'email', 'subject']


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'banner_type', 'display_seconds', 'is_active', 'is_dismissible', 'order', 'created_at']
    list_filter = ['banner_type', 'is_active', 'is_dismissible']
    list_editable = ['is_active', 'is_dismissible', 'order', 'display_seconds']
    search_fields = ['title', 'message']
    fieldsets = (
        (None, {
            'fields': ('title', 'message', 'banner_type')
        }),
        ('Link (Optional)', {
            'fields': ('link_url', 'link_text'),
            'classes': ('collapse',)
        }),
        ('Display Settings', {
            'fields': ('display_seconds', 'is_active', 'is_dismissible', 'order')
        }),
    )
