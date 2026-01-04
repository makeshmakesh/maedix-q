from django.urls import path
from . import views

urlpatterns = [
    path('connect/', views.InstagramConnectView.as_view(), name='instagram_connect'),
    path('oauth/', views.InstagramOAuthRedirectView.as_view(), name='instagram_oauth'),
    path('callback/', views.InstagramCallbackView.as_view(), name='instagram_callback'),
    path('disconnect/', views.InstagramDisconnectView.as_view(), name='instagram_disconnect'),
    path('post/', views.PostToInstagramView.as_view(), name='instagram_post'),
]
