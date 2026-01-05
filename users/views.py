from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from .forms import SignupForm, LoginForm, ProfileForm, UserForm, OTPVerificationForm
from .models import UserProfile, UserStats, EmailOTP
from .otp_utils import send_otp_email, verify_otp
from core.models import Subscription, Plan, Transaction
from core.subscription_utils import get_or_create_free_subscription

User = get_user_model()


class SignupView(View):
    """User registration view"""
    template_name = 'users/signup.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        form = SignupForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
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
                return redirect('dashboard')
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
            return redirect('dashboard')
        form = LoginForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, email=email, password=password)
            if user is not None:
                login(request, user)
                next_url = request.GET.get('next', 'dashboard')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid email or password')
        return render(request, self.template_name, {'form': form})


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
        ).select_related('quiz')[:5]

        # Check Instagram connection status
        instagram_connected = False
        if hasattr(request.user, 'instagram_account'):
            instagram_connected = request.user.instagram_account.is_connected

        return render(request, self.template_name, {
            'stats': stats,
            'recent_videos': recent_videos,
            'instagram_connected': instagram_connected,
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

        return render(request, self.template_name, {
            'profile': profile,
            'stats': stats,
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
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
        # Get user's active subscription
        subscription = Subscription.objects.filter(
            user=request.user
        ).select_related('plan').first()

        # Get available plans for upgrade
        plans = Plan.objects.filter(is_active=True)

        # Get recent transactions
        transactions = Transaction.objects.filter(
            user=request.user
        ).order_by('-created_at')[:10]

        # Calculate usage stats if subscription exists
        usage_stats = []
        if subscription and subscription.plan:
            for feature in subscription.plan.features:
                code = feature.get('code')
                description = feature.get('description')
                limit = feature.get('limit')
                used = subscription.get_usage(code)

                if limit:
                    percentage = min(100, int((used / limit) * 100))
                else:
                    percentage = 0
                    limit = 'Unlimited'

                usage_stats.append({
                    'code': code,
                    'description': description,
                    'limit': limit,
                    'used': used,
                    'remaining': subscription.get_remaining(code) if limit != 'Unlimited' else 'Unlimited',
                    'percentage': percentage,
                })

        context = {
            'subscription': subscription,
            'plans': plans,
            'transactions': transactions,
            'usage_stats': usage_stats,
        }
        return render(request, self.template_name, context)

