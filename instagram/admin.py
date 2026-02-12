from django.contrib import admin
from .models import (
    InstagramAccount, DMFlow, FlowNode, QuickReplyOption,
    FlowSession, FlowExecutionLog, CollectedLead, FlowTemplate,
    APICallLog, QueuedFlowTrigger, DroppedMessage,
    SocialAgent, KnowledgeBase, KnowledgeItem, KnowledgeChunk,
    AINodeConfig, AIConversationMessage, AIUsageLog, AICollectedData
)


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    pass


@admin.register(DMFlow)
class DMFlowAdmin(admin.ModelAdmin):
    pass


@admin.register(FlowNode)
class FlowNodeAdmin(admin.ModelAdmin):
    pass


@admin.register(QuickReplyOption)
class QuickReplyOptionAdmin(admin.ModelAdmin):
    pass


@admin.register(FlowSession)
class FlowSessionAdmin(admin.ModelAdmin):
    pass


@admin.register(FlowExecutionLog)
class FlowExecutionLogAdmin(admin.ModelAdmin):
    pass


@admin.register(CollectedLead)
class CollectedLeadAdmin(admin.ModelAdmin):
    pass


@admin.register(FlowTemplate)
class FlowTemplateAdmin(admin.ModelAdmin):
    pass


@admin.register(APICallLog)
class APICallLogAdmin(admin.ModelAdmin):
    pass


@admin.register(DroppedMessage)
class DroppedMessageAdmin(admin.ModelAdmin):
    pass


@admin.register(QueuedFlowTrigger)
class QueuedFlowTriggerAdmin(admin.ModelAdmin):
    pass


@admin.register(SocialAgent)
class SocialAgentAdmin(admin.ModelAdmin):
    pass


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    pass


@admin.register(KnowledgeItem)
class KnowledgeItemAdmin(admin.ModelAdmin):
    pass


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    pass


@admin.register(AINodeConfig)
class AINodeConfigAdmin(admin.ModelAdmin):
    pass


@admin.register(AIConversationMessage)
class AIConversationMessageAdmin(admin.ModelAdmin):
    pass


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    pass


@admin.register(AICollectedData)
class AICollectedDataAdmin(admin.ModelAdmin):
    pass
