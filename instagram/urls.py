from django.urls import path
from . import views

urlpatterns = [
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
    path('flows/create/', views.FlowCreateView.as_view(), name='flow_create'),
    path('flows/create-from-template/<int:template_id>/', views.FlowCreateFromTemplateView.as_view(), name='flow_create_from_template'),
    path('flows/<int:pk>/edit/', views.FlowEditView.as_view(), name='flow_edit'),
    path('flows/<int:pk>/delete/', views.FlowDeleteView.as_view(), name='flow_delete'),
    path('flows/<int:pk>/toggle-active/', views.FlowToggleActiveView.as_view(), name='flow_toggle_active'),
    path('flows/<int:pk>/sessions/', views.FlowSessionsView.as_view(), name='flow_sessions'),

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

    # Webhook
    path('webhook/', views.InstagramWebhookView.as_view(), name='instagram_webhook'),

    # Facebook App Callback URLs (Required for App Review)
    path('data-deletion/', views.DataDeletionCallbackView.as_view(), name='instagram_data_deletion'),
    path('deauthorize/', views.DeauthorizationCallbackView.as_view(), name='instagram_deauthorize'),
]
