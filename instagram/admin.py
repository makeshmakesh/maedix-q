from django.contrib import admin
from .models import (
    InstagramAccount, DMFlow, FlowNode, QuickReplyOption,
    FlowSession, FlowExecutionLog, CollectedLead, FlowTemplate,
    APICallLog, QueuedFlowTrigger,
    # AI Models
    SocialAgent, KnowledgeBase, KnowledgeItem, KnowledgeChunk,
    AINodeConfig, AIConversationMessage, AIUsageLog, AICollectedData
)


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'username', 'is_active', 'total_dms_sent', 'total_comments_replied', 'token_expires_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('user__email', 'username')
    readonly_fields = ('total_dms_sent', 'total_comments_replied', 'created_at', 'updated_at')


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


# =============================================================================
# Rate Limiting Admin
# =============================================================================

@admin.register(APICallLog)
class APICallLogAdmin(admin.ModelAdmin):
    list_display = ('account', 'call_type', 'endpoint', 'recipient_id', 'success', 'sent_at')
    list_filter = ('call_type', 'success', 'sent_at')
    search_fields = ('account__username', 'endpoint', 'recipient_id')
    readonly_fields = ('sent_at',)
    raw_id_fields = ('account',)
    date_hierarchy = 'sent_at'
    ordering = ('-sent_at',)


@admin.register(QueuedFlowTrigger)
class QueuedFlowTriggerAdmin(admin.ModelAdmin):
    list_display = ('id', 'account', 'flow', 'trigger_type', 'status', 'created_at', 'processed_at')
    list_filter = ('status', 'trigger_type', 'created_at')
    search_fields = ('account__username', 'flow__title', 'instagram_event_id')
    readonly_fields = ('created_at',)
    raw_id_fields = ('account', 'flow')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('account', 'flow', 'trigger_type', 'status')
        }),
        ('Event Details', {
            'fields': ('instagram_event_id', 'trigger_context')
        }),
        ('Processing', {
            'fields': ('error_message', 'created_at', 'processed_at')
        }),
    )


# =============================================================================
# AI Social Agent Admin
# =============================================================================

@admin.register(SocialAgent)
class SocialAgentAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'tone', 'is_active', 'total_conversations', 'total_messages_sent', 'created_at')
    list_filter = ('is_active', 'tone')
    search_fields = ('name', 'user__email', 'personality')
    readonly_fields = ('total_conversations', 'total_messages_sent', 'created_at', 'updated_at')
    raw_id_fields = ('user',)


class KnowledgeItemInline(admin.TabularInline):
    model = KnowledgeItem
    extra = 0
    fields = ('title', 'item_type', 'processing_status', 'chunk_count', 'token_count')
    readonly_fields = ('processing_status', 'chunk_count', 'token_count')


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'agent', 'total_items', 'total_chunks', 'total_tokens', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'user__email', 'agent__name')
    readonly_fields = ('total_items', 'total_chunks', 'total_tokens', 'created_at', 'updated_at')
    raw_id_fields = ('user', 'agent')
    inlines = [KnowledgeItemInline]


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    fields = ('chunk_index', 'token_count', 'content')
    readonly_fields = ('chunk_index', 'token_count', 'content')
    max_num = 10


@admin.register(KnowledgeItem)
class KnowledgeItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'knowledge_base', 'item_type', 'processing_status', 'chunk_count', 'token_count', 'created_at')
    list_filter = ('item_type', 'processing_status')
    search_fields = ('title', 'file_name', 'knowledge_base__name')
    readonly_fields = ('chunk_count', 'token_count', 'embedding_cost', 'processed_at', 'created_at', 'updated_at')
    raw_id_fields = ('knowledge_base',)
    inlines = [KnowledgeChunkInline]


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'knowledge_item', 'chunk_index', 'token_count', 'created_at')
    search_fields = ('content', 'knowledge_item__title')
    readonly_fields = ('created_at',)
    raw_id_fields = ('knowledge_item',)


class AIConversationMessageInline(admin.TabularInline):
    model = AIConversationMessage
    extra = 0
    fields = ('role', 'content', 'input_tokens', 'output_tokens', 'created_at')
    readonly_fields = ('role', 'content', 'input_tokens', 'output_tokens', 'created_at')
    ordering = ('created_at',)


@admin.register(AINodeConfig)
class AINodeConfigAdmin(admin.ModelAdmin):
    list_display = ('flow_node', 'agent', 'max_turns', 'on_goal_complete', 'created_at')
    list_filter = ('on_goal_complete', 'on_failure')
    search_fields = ('flow_node__flow__title', 'agent__name', 'goal')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('flow_node', 'agent', 'goal_complete_node', 'failure_node', 'max_turns_node')
    filter_horizontal = ('additional_knowledge_bases',)


@admin.register(AIConversationMessage)
class AIConversationMessageAdmin(admin.ModelAdmin):
    list_display = ('session', 'role', 'content_preview', 'input_tokens', 'output_tokens', 'created_at')
    list_filter = ('role',)
    search_fields = ('content', 'session__instagram_username')
    readonly_fields = ('created_at',)
    raw_id_fields = ('session', 'ai_config')

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = 'Content'


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'usage_type', 'model', 'total_tokens', 'cost_usd', 'credits_charged', 'created_at')
    list_filter = ('usage_type', 'model')
    search_fields = ('user__email',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('user', 'session', 'agent')
    date_hierarchy = 'created_at'


@admin.register(AICollectedData)
class AICollectedDataAdmin(admin.ModelAdmin):
    list_display = ('session', 'is_complete', 'completion_percentage', 'turn_count', 'created_at')
    list_filter = ('is_complete',)
    search_fields = ('session__instagram_username',)
    readonly_fields = ('completion_percentage', 'fields_collected', 'created_at', 'updated_at')
    raw_id_fields = ('session', 'ai_config')
