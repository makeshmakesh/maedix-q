import json
import logging
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import IntegrityError
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from .forms import SignupForm, LoginForm, ProfileForm, UserForm, OTPVerificationForm
from .models import UserProfile, UserStats, EmailOTP
from .otp_utils import send_otp_email, verify_otp
from core.models import Configuration, Subscription, Plan, Transaction
from core.subscription_utils import get_or_create_free_subscription
from core.utils import get_user_country

User = get_user_model()
logger = logging.getLogger(__name__)


class SignupView(View):
    """User registration view"""
    template_name = 'users/signup.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('flow_list')
        form = SignupForm()
        google_client_id = Configuration.get_value('google_oauth_client_id', '')
        return render(request, self.template_name, {'form': form, 'google_client_id': google_client_id})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('flow_list')
        form = SignupForm(request.POST)
        if form.is_valid():
            # Create user as inactive (pending email verification)
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            # Send OTP to user's email
            try:
                send_otp_email(user)
                # Store user ID in session for OTP verification
                request.session['pending_user_id'] = user.id
                messages.info(request, f'A verification code has been sent to {user.email}')
                return redirect('verify_otp')
            except Exception as e:
                # If email fails, delete the user and show error
                user.delete()
                messages.error(request, 'Failed to send verification email. Please try again.')
                return render(request, self.template_name, {'form': form})

        return render(request, self.template_name, {'form': form})


class OTPVerificationView(View):
    """View for verifying OTP during signup"""
    template_name = 'users/verify-otp.html'

    def get(self, request):
        # Check if there's a pending user in session
        pending_user_id = request.session.get('pending_user_id')
        if not pending_user_id:
            messages.error(request, 'No pending verification. Please sign up first.')
            return redirect('signup')

        try:
            user = User.objects.get(id=pending_user_id, is_active=False)
        except User.DoesNotExist:
            del request.session['pending_user_id']
            messages.error(request, 'Invalid session. Please sign up again.')
            return redirect('signup')

        form = OTPVerificationForm()
        return render(request, self.template_name, {
            'form': form,
            'email': user.email,
        })

    def post(self, request):
        pending_user_id = request.session.get('pending_user_id')
        if not pending_user_id:
            messages.error(request, 'No pending verification. Please sign up first.')
            return redirect('signup')

        try:
            user = User.objects.get(id=pending_user_id, is_active=False)
        except User.DoesNotExist:
            del request.session['pending_user_id']
            messages.error(request, 'Invalid session. Please sign up again.')
            return redirect('signup')

        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp_code = form.cleaned_data['otp']
            success, message = verify_otp(user, otp_code)

            if success:
                # Create profile and stats for verified user
                UserProfile.objects.get_or_create(user=user)
                UserStats.objects.get_or_create(user=user)
                # Create free subscription for new user
                get_or_create_free_subscription(user)

                # Clean up session
                del request.session['pending_user_id']

                # Log the user in
                login(request, user)
                messages.success(request, 'Email verified! Account created successfully. You are on the Free plan.')
                return redirect('flow_list')
            else:
                messages.error(request, message)

        return render(request, self.template_name, {
            'form': form,
            'email': user.email,
        })


class ResendOTPView(View):
    """View for resending OTP"""

    def post(self, request):
        pending_user_id = request.session.get('pending_user_id')
        if not pending_user_id:
            messages.error(request, 'No pending verification. Please sign up first.')
            return redirect('signup')

        try:
            user = User.objects.get(id=pending_user_id, is_active=False)
        except User.DoesNotExist:
            del request.session['pending_user_id']
            messages.error(request, 'Invalid session. Please sign up again.')
            return redirect('signup')

        # Check if we can resend (rate limiting - 1 minute cooldown)
        last_otp = EmailOTP.objects.filter(user=user).order_by('-created_at').first()
        if last_otp:
            time_since_last = timezone.now() - last_otp.created_at
            if time_since_last.total_seconds() < 60:
                remaining = 60 - int(time_since_last.total_seconds())
                messages.warning(request, f'Please wait {remaining} seconds before requesting a new code.')
                return redirect('verify_otp')

        try:
            send_otp_email(user)
            messages.success(request, f'A new verification code has been sent to {user.email}')
        except Exception:
            messages.error(request, 'Failed to send verification email. Please try again.')

        return redirect('verify_otp')


class LoginView(View):
    """User login view"""
    template_name = 'users/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('flow_list')
        form = LoginForm()
        google_client_id = Configuration.get_value('google_oauth_client_id', '')
        return render(request, self.template_name, {'form': form, 'google_client_id': google_client_id})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('flow_list')
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, email=email, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get('next', '')
                # Validate redirect URL to prevent open redirect attacks
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    return redirect(next_url)
                return redirect('flow_list')
            else:
                messages.error(request, 'Invalid email or password')
        return render(request, self.template_name, {'form': form})


class GoogleAuthView(View):
    """Google OAuth2 sign-in: redirects to Google or handles callback"""

    def get(self, request):
        code = request.GET.get('code')
        error = request.GET.get('error')

        client_id = Configuration.get_value('google_oauth_client_id', '')
        if not client_id:
            messages.error(request, 'Google Sign-In is not configured')
            return redirect('login')

        redirect_uri = f'{request.scheme}://{request.get_host()}/users/google-auth/callback/'

        # If no code, redirect to Google consent screen
        if not code and not error:
            params = urlencode({
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'openid email profile',
                'access_type': 'online',
                'prompt': 'select_account',
            })
            return redirect(f'https://accounts.google.com/o/oauth2/v2/auth?{params}')

        # Handle error from Google
        if error:
            messages.error(request, 'Google sign-in was cancelled or failed.')
            return redirect('login')

        # Exchange authorization code for tokens
        client_secret = Configuration.get_value('google_oauth_client_secret', '')
        if not client_secret:
            messages.error(request, 'Google Sign-In is not configured')
            return redirect('login')

        try:
            token_data = urlencode({
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code',
            }).encode()
            token_request = Request('https://oauth2.googleapis.com/token', data=token_data)
            token_request.add_header('Content-Type', 'application/x-www-form-urlencoded')
            with urlopen(token_request) as resp:
                token_response = json.loads(resp.read())
        except Exception:
            logger.exception('Google token exchange failed')
            messages.error(request, 'Google sign-in failed. Please try again.')
            return redirect('login')

        # Verify the ID token
        id_token_value = token_response.get('id_token')
        if not id_token_value:
            messages.error(request, 'Google sign-in failed. Please try again.')
            return redirect('login')

        try:
            idinfo = id_token.verify_oauth2_token(id_token_value, google_requests.Request(), client_id)
        except ValueError:
            messages.error(request, 'Invalid Google token. Please try again.')
            return redirect('login')

        email = idinfo.get('email')
        if not email:
            messages.error(request, 'Email not provided by Google')
            return redirect('login')

        # Try to find existing user
        try:
            user = User.objects.get(email=email)
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=['is_active'])
        except User.DoesNotExist:
            # Create new user
            try:
                user = User(
                    email=email,
                    first_name=idinfo.get('given_name', ''),
                    last_name=idinfo.get('family_name', ''),
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()

                # Create profile, stats, and free subscription (same as OTP verification flow)
                UserProfile.objects.get_or_create(user=user)
                UserStats.objects.get_or_create(user=user)
                get_or_create_free_subscription(user)
            except IntegrityError:
                # Race condition: user was created between our check and save
                user = User.objects.get(email=email)

        login(request, user)
        return redirect('flow_list')


class LogoutView(View):
    """User logout view"""

    def post(self, request):
        logout(request)
        messages.success(request, 'You have been logged out')
        return redirect('home')

    def get(self, request):
        return redirect('home')


class DashboardView(LoginRequiredMixin, View):
    """User dashboard - main hub after login"""
    template_name = 'users/dashboard.html'

    def get(self, request):
        from quiz.models import GeneratedVideo

        # Get or create user stats
        stats, _ = UserStats.objects.get_or_create(user=request.user)

        # Get recent generated videos
        recent_videos = GeneratedVideo.objects.filter(
            user=request.user
        ).select_related('quiz')[:15]

        # Check Instagram connection status
        instagram_connected = False
        if hasattr(request.user, 'instagram_account'):
            instagram_connected = request.user.instagram_account.is_connected

        # Check YouTube connection status
        youtube_connected = False
        if hasattr(request.user, 'youtube_account'):
            youtube_connected = request.user.youtube_account.is_connected

        return render(request, self.template_name, {
            'stats': stats,
            'recent_videos': recent_videos,
            'instagram_connected': instagram_connected,
            'youtube_connected': youtube_connected,
        })


class ProfileView(LoginRequiredMixin, View):
    """View user profile"""
    template_name = 'users/profile.html'

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        stats, _ = UserStats.objects.get_or_create(user=request.user)

        # Check Instagram connection status
        instagram_connected = False
        instagram_account = None
        if hasattr(request.user, 'instagram_account'):
            instagram_account = request.user.instagram_account
            instagram_connected = instagram_account.is_connected

        # Check YouTube connection status
        youtube_connected = False
        youtube_account = None
        if hasattr(request.user, 'youtube_account'):
            youtube_account = request.user.youtube_account
            youtube_connected = youtube_account.is_connected

        return render(request, self.template_name, {
            'profile': profile,
            'stats': stats,
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
            'youtube_connected': youtube_connected,
            'youtube_account': youtube_account,
        })


class ProfileEditView(LoginRequiredMixin, View):
    """Edit user profile"""
    template_name = 'users/profile-edit.html'

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=profile)
        return render(request, self.template_name, {
            'user_form': user_form,
            'profile_form': profile_form,
        })

    def post(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')

        return render(request, self.template_name, {
            'user_form': user_form,
            'profile_form': profile_form,
        })


class SettingsView(LoginRequiredMixin, View):
    """User settings page"""
    template_name = 'users/settings.html'

    def get(self, request):
        return render(request, self.template_name)


class SubscriptionView(LoginRequiredMixin, View):
    """User subscription management page"""
    template_name = 'users/subscription.html'

    def get(self, request):
        from instagram.models import DMFlow

        # Get user's active subscription
        subscription = Subscription.objects.filter(
            user=request.user
        ).select_related('plan').first()

        # Get available plans for upgrade
        plans = Plan.objects.filter(is_active=True).order_by('order')

        # Get user's country for pricing
        user_country = get_user_country(request)

        # Build plans with user-specific pricing
        plans_with_pricing = []
        for plan in plans:
            pricing = plan.get_pricing_for_country(user_country)
            plans_with_pricing.append({
                'plan': plan,
                'price_monthly': pricing['monthly'],
                'price_yearly': pricing['yearly'],
                'currency': pricing['currency'],
                'symbol': pricing['symbol'],
            })

        # Get recent transactions
        transactions = Transaction.objects.filter(
            user=request.user
        ).order_by('-created_at')[:10]

        # Calculate DM Flow stats
        flow_count = DMFlow.objects.filter(user=request.user).count()
        flow_limit = None
        flow_remaining = None
        flow_percentage = 0

        if subscription and subscription.plan:
            feature = subscription.plan.get_feature('ig_flow_builder')
            if feature:
                flow_limit = feature.get('limit')
                if flow_limit:
                    flow_remaining = max(0, flow_limit - flow_count)
                    flow_percentage = min(100, int((flow_count / flow_limit) * 100))

        context = {
            'subscription': subscription,
            'plans': plans_with_pricing,
            'transactions': transactions,
            'automation_count': flow_count,
            'automation_limit': flow_limit,
            'automation_remaining': flow_remaining,
            'automation_percentage': flow_percentage,
        }
        return render(request, self.template_name, context)

