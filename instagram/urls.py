from django.urls import path
from . import views

urlpatterns = [
    # Connection management
    path('connect/', views.InstagramConnectView.as_view(), name='instagram_connect'),
    path('oauth/', views.InstagramOAuthRedirectView.as_view(), name='instagram_oauth'),
    path('callback/', views.InstagramCallbackView.as_view(), name='instagram_callback'),
    path('disconnect/', views.InstagramDisconnectView.as_view(), name='instagram_disconnect'),
    path('subscribe/', views.InstagramWebhookSubscribeView.as_view(), name='instagram_subscribe'),
    path('post/', views.InstagramPostPageView.as_view(), name='instagram_post_page'),

    # Automation management
    path('automation/', views.AutomationLandingView.as_view(), name='instagram_automation_landing'),
    path('automation/dashboard/', views.AutomationListView.as_view(), name='instagram_automation_list'),
    path('automation/create/', views.AutomationCreateView.as_view(), name='instagram_automation_create'),
    path('api/posts/', views.InstagramPostsAPIView.as_view(), name='instagram_api_posts'),
    path('automation/<int:pk>/edit/', views.AutomationEditView.as_view(), name='instagram_automation_edit'),
    path('automation/<int:pk>/delete/', views.AutomationDeleteView.as_view(), name='instagram_automation_delete'),
    path('automation/account/', views.AccountAutomationView.as_view(), name='instagram_automation_account'),

    # Webhook
    path('webhook/', views.InstagramWebhookView.as_view(), name='instagram_webhook'),

    # Facebook App Callback URLs (Required for App Review)
    path('data-deletion/', views.DataDeletionCallbackView.as_view(), name='instagram_data_deletion'),
    path('deauthorize/', views.DeauthorizationCallbackView.as_view(), name='instagram_deauthorize'),
]
