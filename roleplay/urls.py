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

    # Credit purchase
    path('credits/', views.PurchaseCreditsView.as_view(), name='purchase_credits'),
    path('credits/checkout/', views.CreditCheckoutView.as_view(), name='credit_checkout'),
    path('credits/success/', views.CreditPaymentSuccessView.as_view(), name='credit_success'),
    path('credits/failed/', views.CreditPaymentFailedView.as_view(), name='credit_failed'),
]
