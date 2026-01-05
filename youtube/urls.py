from django.urls import path
from . import views

urlpatterns = [
    path('connect/', views.YouTubeConnectView.as_view(), name='youtube_connect'),
    path('oauth/', views.YouTubeOAuthRedirectView.as_view(), name='youtube_oauth'),
    path('callback/', views.YouTubeCallbackView.as_view(), name='youtube_callback'),
    path('disconnect/', views.YouTubeDisconnectView.as_view(), name='youtube_disconnect'),
    path('post/', views.YouTubePostView.as_view(), name='youtube_post'),
]
