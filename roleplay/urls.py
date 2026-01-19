from django.urls import path
from . import views

app_name = 'roleplay'

urlpatterns = [
    # Bot listing and discovery
    path('', views.RoleplayHomeView.as_view(), name='home'),

    # Session management
    path('start/<uuid:bot_id>/', views.RoleplayStartView.as_view(), name='start'),
    path('session/<uuid:session_id>/', views.RoleplaySessionView.as_view(), name='session'),
    path('session/<uuid:session_id>/end/', views.RoleplayEndSessionView.as_view(), name='end_session'),
]
