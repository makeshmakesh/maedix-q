from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('verify-otp/', views.OTPVerificationView.as_view(), name='verify_otp'),
    path('resend-otp/', views.ResendOTPView.as_view(), name='resend_otp'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('google-auth/', views.GoogleAuthView.as_view(), name='google_auth'),
    path('google-auth/callback/', views.GoogleAuthView.as_view(), name='google_auth_callback'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('settings/', views.SettingsView.as_view(), name='settings'),
    path('subscription/', views.SubscriptionView.as_view(), name='subscription'),

    # Password Reset URLs
    path('password/reset/', auth_views.PasswordResetView.as_view(
        template_name='users/password-reset.html',
        email_template_name='users/emails/password-reset-email.html',
        subject_template_name='users/emails/password-reset-subject.txt',
        success_url='/users/password/reset/done/'
    ), name='password_reset'),

    path('password/reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='users/password-reset-done.html'
    ), name='password_reset_done'),

    path('password/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='users/password-reset-confirm.html',
        success_url='/users/password/reset/complete/'
    ), name='password_reset_confirm'),

    path('password/reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='users/password-reset-complete.html'
    ), name='password_reset_complete'),
]
