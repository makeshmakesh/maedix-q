from django.urls import path
from . import views
from . import ai_views
from . import admin_views

urlpatterns = [
    # Admin Dashboard
    path('admin/dashboard/', admin_views.AdminDashboardView.as_view(), name='instagram_admin_dashboard'),
    path('admin/queue/', admin_views.AdminQueuedFlowsView.as_view(), name='instagram_admin_queue'),
    path('admin/data-deletion/', admin_views.AdminDataDeletionView.as_view(), name='instagram_admin_data_deletion'),

    # Connection management
    path('connect/', views.InstagramConnectView.as_view(), name='instagram_connect'),
    path('oauth/', views.InstagramOAuthRedirectView.as_view(), name='instagram_oauth'),
    path('callback/', views.InstagramCallbackView.as_view(), name='instagram_callback'),
    path('disconnect/', views.InstagramDisconnectView.as_view(), name='instagram_disconnect'),
    path('subscribe/', views.InstagramWebhookSubscribeView.as_view(), name='instagram_subscribe'),
    path('unsubscribe/', views.InstagramWebhookUnsubscribeView.as_view(), name='instagram_unsubscribe'),
    path('post/', views.InstagramPostPageView.as_view(), name='instagram_post_page'),

    # Instagram Posts API
    path('api/posts/', views.InstagramPostsAPIView.as_view(), name='instagram_api_posts'),

    # DM Flow Builder
    path('flows/', views.FlowListView.as_view(), name='flow_list'),
    path('flows/help/', views.FlowBuilderHelpView.as_view(), name='flow_builder_help'),
    path('flows/templates/', views.FlowTemplatesView.as_view(), name='flow_templates'),
    path('flows/templates/<int:template_id>/', views.FlowTemplateDetailView.as_view(), name='flow_template_detail'),
    path('flows/create/', views.FlowCreateView.as_view(), name='flow_create'),
    path('flows/<int:pk>/edit/', views.FlowEditView.as_view(), name='flow_edit'),
    path('flows/<int:pk>/wizard/', views.FlowEditWizardView.as_view(), name='flow_edit_wizard'),
    path('flows/<int:pk>/delete/', views.FlowDeleteView.as_view(), name='flow_delete'),
    path('flows/<int:pk>/toggle-active/', views.FlowToggleActiveView.as_view(), name='flow_toggle_active'),
    path('flows/<int:pk>/sessions/', views.FlowSessionsView.as_view(), name='flow_sessions'),
    path('flows/<int:pk>/sessions/<int:session_id>/', views.FlowSessionDetailView.as_view(), name='flow_session_detail'),

    # Flow Node API endpoints
    path('flows/<int:flow_id>/nodes/', views.FlowNodeCreateView.as_view(), name='flow_node_create'),
    path('flows/<int:flow_id>/nodes/<int:node_id>/', views.FlowNodeDetailView.as_view(), name='flow_node_detail'),
    path('flows/<int:flow_id>/nodes/<int:node_id>/update/', views.FlowNodeUpdateView.as_view(), name='flow_node_update'),
    path('flows/<int:flow_id>/nodes/<int:node_id>/delete/', views.FlowNodeDeleteView.as_view(), name='flow_node_delete'),
    path('flows/<int:flow_id>/nodes/reorder/', views.FlowNodeReorderView.as_view(), name='flow_node_reorder'),
    path('flows/<int:pk>/save-visual/', views.FlowSaveVisualView.as_view(), name='flow_save_visual'),

    # Leads / CRM
    path('leads/', views.LeadsListView.as_view(), name='leads_list'),
    path('leads/export/', views.LeadsExportView.as_view(), name='leads_export'),
    path('leads/<int:pk>/', views.LeadDetailView.as_view(), name='lead_detail'),

    # Queued Flow Triggers
    path('queue/', views.QueuedFlowListView.as_view(), name='queued_flows'),
    path('queue/<int:pk>/trigger/', views.QueuedFlowTriggerView.as_view(), name='queued_flow_trigger'),
    path('queue/<int:pk>/delete/', views.QueuedFlowDeleteView.as_view(), name='queued_flow_delete'),

    # Internal API (Lambda → Django)
    path('api/internal/process-trigger/<int:pk>/', views.ProcessQueuedTriggerAPIView.as_view(), name='internal_process_trigger'),

    # Webhook
    path('webhook/', views.InstagramWebhookView.as_view(), name='instagram_webhook'),

    # Facebook App Callback URLs (Required for App Review)
    path('data-deletion/', views.DataDeletionCallbackView.as_view(), name='instagram_data_deletion'),
    path('deauthorize/', views.DeauthorizationCallbackView.as_view(), name='instagram_deauthorize'),

    # ==========================================================================
    # AI Social Agent URLs
    # ==========================================================================

    # Social Agents
    path('ai/agents/', ai_views.AgentListView.as_view(), name='ai_agent_list'),
    path('ai/agents/create/', ai_views.AgentCreateView.as_view(), name='ai_agent_create'),
    path('ai/agents/<int:agent_id>/', ai_views.AgentDetailView.as_view(), name='ai_agent_detail'),
    path('ai/agents/<int:agent_id>/edit/', ai_views.AgentEditView.as_view(), name='ai_agent_edit'),
    path('ai/agents/<int:agent_id>/delete/', ai_views.AgentDeleteView.as_view(), name='ai_agent_delete'),

    # Knowledge Bases
    path('ai/knowledge/', ai_views.KnowledgeBaseCreateView.as_view(), name='ai_kb_create'),
    path('ai/knowledge/<int:kb_id>/', ai_views.KnowledgeBaseDetailView.as_view(), name='ai_kb_detail'),
    path('ai/knowledge/<int:kb_id>/delete/', ai_views.KnowledgeBaseDeleteView.as_view(), name='ai_kb_delete'),
    path('ai/knowledge/<int:kb_id>/add-text/', ai_views.KnowledgeItemAddTextView.as_view(), name='ai_kb_add_text'),
    path('ai/knowledge/<int:kb_id>/upload/', ai_views.KnowledgeItemUploadView.as_view(), name='ai_kb_upload'),
    path('ai/knowledge/item/<int:item_id>/delete/', ai_views.KnowledgeItemDeleteView.as_view(), name='ai_kb_item_delete'),
    path('ai/knowledge/item/<int:item_id>/reprocess/', ai_views.KnowledgeItemReprocessView.as_view(), name='ai_kb_item_reprocess'),

    # AI Node Configuration
    path('ai/node/<int:node_id>/config/', ai_views.AINodeConfigView.as_view(), name='ai_node_config'),

    # AI Collected Data
    path('ai/data/', ai_views.AICollectedDataListView.as_view(), name='ai_collected_data_list'),
    path('ai/data/export/', ai_views.AICollectedDataExportView.as_view(), name='ai_collected_data_export'),
    path('ai/data/session/<int:session_id>/', ai_views.AICollectedDataDetailView.as_view(), name='ai_collected_data_detail'),

    # AI Usage Stats
    path('ai/usage/', ai_views.AIUsageStatsView.as_view(), name='ai_usage_stats'),

    # AI API Endpoints
    path('api/ai/agents/<int:agent_id>/preview/', ai_views.AgentPreviewAPIView.as_view(), name='ai_agent_preview_api'),
    path('api/ai/knowledge/<int:kb_id>/search/', ai_views.KnowledgeSearchAPIView.as_view(), name='ai_kb_search_api'),
    path('api/ai/node/<int:node_id>/schema/', ai_views.AINodeSchemaAPIView.as_view(), name='ai_node_schema_api'),
]
