from django.urls import path
from . import views
from instagram.views import AutomationLandingView

urlpatterns = [
    path('', AutomationLandingView.as_view(), name='home'),
    path('instagram-automation/', AutomationLandingView.as_view(), name='instagram_automation_landing'),
    path('about/', views.AboutPage.as_view(), name='about'),
    path('pricing/', views.PricingPage.as_view(), name='pricing'),
    path('contact/', views.ContactPage.as_view(), name='contact'),
    path('terms/', views.TermsPage.as_view(), name='terms'),
    path('privacy-policy/', views.PrivacyPolicyPage.as_view(), name='privacy_policy'),
    path('refund-policy/', views.RefundPolicyPage.as_view(), name='refund_policy'),

    # Payment URLs
    path('payment/checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('payment/validate-coupon/', views.ValidateCouponView.as_view(), name='validate_coupon'),
    path('payment/success/', views.PaymentSuccessView.as_view(), name='payment_success'),
    path('payment/success/page/', views.PaymentSuccessPageView.as_view(), name='payment_success_page'),
    path('payment/failed/', views.PaymentFailedView.as_view(), name='payment_failed'),
    path('payment/webhook/', views.PaymentWebhookView.as_view(), name='payment_webhook'),

    # Credits
    path('credits/', views.PurchaseCreditsView.as_view(), name='purchase_credits'),
    path('credits/checkout/', views.CreditCheckoutView.as_view(), name='credit_checkout'),
    path('credits/success/', views.CreditPaymentSuccessView.as_view(), name='credit_success'),
    path('credits/failed/', views.CreditPaymentFailedView.as_view(), name='credit_failed'),

    # Link redirect (watermark/branding page)
    path('go/', views.LinkRedirectView.as_view(), name='link_redirect'),
]
