from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from .forms import SignupForm, LoginForm, ProfileForm, UserForm
from .models import UserProfile, UserStats
from core.models import Subscription, Plan, Transaction
from core.subscription_utils import get_or_create_free_subscription


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
            user = form.save()
            # Create profile and stats for new user
            UserProfile.objects.create(user=user)
            UserStats.objects.create(user=user)
            # Create free subscription for new user
            get_or_create_free_subscription(user)
            login(request, user)
            messages.success(request, 'Account created successfully! You are on the Free plan.')
            return redirect('dashboard')
        return render(request, self.template_name, {'form': form})


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
        # Get or create user stats
        stats, _ = UserStats.objects.get_or_create(user=request.user)
        return render(request, self.template_name, {'stats': stats})


class ProfileView(LoginRequiredMixin, View):
    """View user profile"""
    template_name = 'users/profile.html'

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        stats, _ = UserStats.objects.get_or_create(user=request.user)
        return render(request, self.template_name, {
            'profile': profile,
            'stats': stats,
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

