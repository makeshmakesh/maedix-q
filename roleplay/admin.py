from django.contrib import admin
from .models import RolePlayBot, RoleplaySession, CreditTransaction


@admin.register(RolePlayBot)
class RolePlayBotAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'voice', 'required_credits', 'is_active', 'order']
    list_filter = ['category', 'is_active', 'voice']
    search_fields = ['name', 'description']
    list_editable = ['is_active', 'order']
    ordering = ['order', 'name']
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'avatar_url')
        }),
        ('AI Configuration', {
            'fields': ('system_prompt', 'voice', 'custom_configuration')
        }),
        ('Settings', {
            'fields': ('category', 'required_credits', 'is_active', 'order')
        }),
    )


@admin.register(RoleplaySession)
class RoleplaySessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'bot', 'status', 'duration_seconds', 'credits_used', 'started_at']
    list_filter = ['status', 'bot', 'started_at']
    search_fields = ['user__email', 'bot__name']
    readonly_fields = ['id', 'started_at', 'completed_at']
    date_hierarchy = 'started_at'


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ['user', 'credits', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['status', 'currency', 'created_at']
    search_fields = ['user__email', 'razorpay_order_id', 'razorpay_payment_id']
    readonly_fields = ['id', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
