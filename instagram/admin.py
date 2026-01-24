from django.contrib import admin
from .models import (
    InstagramAccount, DMFlow, FlowNode, QuickReplyOption,
    FlowSession, FlowExecutionLog, CollectedLead, FlowTemplate
)


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'username', 'is_active', 'token_expires_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('user__email', 'username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DMFlow)
class DMFlowAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'trigger_type', 'is_active', 'total_triggered', 'total_completed', 'created_at')
    list_filter = ('is_active', 'trigger_type')
    search_fields = ('title', 'user__email', 'keywords')
    readonly_fields = ('total_triggered', 'total_completed', 'created_at', 'updated_at')
    raw_id_fields = ('user',)


class QuickReplyOptionInline(admin.TabularInline):
    model = QuickReplyOption
    fk_name = 'node'  # Specify which FK to use since model has two FKs to FlowNode
    extra = 0
    fields = ('title', 'payload', 'order', 'target_node')
    raw_id_fields = ('target_node',)


@admin.register(FlowNode)
class FlowNodeAdmin(admin.ModelAdmin):
    list_display = ('flow', 'order', 'node_type', 'name', 'created_at')
    list_filter = ('node_type',)
    search_fields = ('flow__title', 'name')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('flow', 'next_node')
    inlines = [QuickReplyOptionInline]


@admin.register(QuickReplyOption)
class QuickReplyOptionAdmin(admin.ModelAdmin):
    list_display = ('node', 'title', 'payload', 'order', 'target_node')
    search_fields = ('title', 'payload', 'node__flow__title')
    raw_id_fields = ('node', 'target_node')


@admin.register(FlowSession)
class FlowSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'flow', 'instagram_username', 'status', 'created_at', 'completed_at')
    list_filter = ('status',)
    search_fields = ('instagram_username', 'instagram_scoped_id', 'flow__title')
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    raw_id_fields = ('flow', 'current_node')


@admin.register(FlowExecutionLog)
class FlowExecutionLogAdmin(admin.ModelAdmin):
    list_display = ('session', 'action', 'node', 'created_at')
    list_filter = ('action',)
    search_fields = ('session__instagram_username',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('session', 'node')


@admin.register(CollectedLead)
class CollectedLeadAdmin(admin.ModelAdmin):
    list_display = ('instagram_username', 'user', 'name', 'email', 'phone', 'is_follower', 'flow', 'created_at')
    list_filter = ('is_follower',)
    search_fields = ('instagram_username', 'name', 'email', 'phone', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user', 'flow', 'session')


@admin.register(FlowTemplate)
class FlowTemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'is_active', 'order', 'created_at')
    list_filter = ('is_active', 'category')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    list_editable = ('is_active', 'order')
    ordering = ('order', 'title')
