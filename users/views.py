import json
import logging
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen, Request

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from .forms import SignupForm, LoginForm, ProfileForm, UserForm, OTPVerificationForm, ProfileLinkForm
from .models import (
    UserProfile, UserStats, EmailOTP, ProfileLink, ProfilePageView,
    ProfileLinkClick, generate_unique_username, hash_ip,
)
from .otp_utils import send_otp_email, verify_otp
from core.models import Configuration, Subscription, Plan, Transaction
from core.subscription_utils import get_or_create_free_subscription, get_user_subscription
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
                    username=generate_unique_username(email),
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


class DeleteAccountView(LoginRequiredMixin, View):
    """Permanently delete user account and all associated data"""

    def post(self, request):
        user = request.user

        if user.has_usable_password():
            # Password-based account: verify password
            password = request.POST.get('password', '')
            if not user.check_password(password):
                messages.error(request, 'Incorrect password.')
                return redirect('settings')
        else:
            # Google OAuth account: verify email
            confirm_email = request.POST.get('confirm_email', '').strip().lower()
            if confirm_email != user.email.lower():
                messages.error(request, 'Email does not match.')
                return redirect('settings')

        email = user.email
        logger.info(f"Account deletion requested by {email}")

        # Unsubscribe from Instagram webhooks before deleting
        if hasattr(user, 'instagram_account'):
            ig = user.instagram_account
            if ig.instagram_user_id and ig.access_token:
                try:
                    import requests as http_requests
                    url = f"https://graph.instagram.com/v21.0/{ig.instagram_user_id}/subscribed_apps"
                    http_requests.delete(url, params={"access_token": ig.access_token}, timeout=10)
                except Exception as e:
                    logger.warning(f"Failed to unsubscribe webhooks on account deletion: {e}")

        logout(request)
        User.objects.filter(email=email).delete()

        logger.info(f"Account deleted: {email}")
        messages.success(request, 'Your account has been permanently deleted.')
        return redirect('login')


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


# ─── Public Profile Views ───────────────────────────────────────────────────


class PublicProfileView(View):
    """Public profile page at /@username/"""

    def get(self, request, username):
        profile_user = get_object_or_404(User, username__iexact=username, is_active=True)
        profile, _ = UserProfile.objects.get_or_create(user=profile_user)
        links = ProfileLink.objects.filter(user=profile_user, is_active=True)

        # Log page view
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ',' in ip:
            ip = ip.split(',')[0].strip()
        referrer = request.META.get('HTTP_REFERER', '')
        # Validate referrer is a proper URL before storing
        if referrer:
            try:
                parsed = urlparse(referrer)
                if not parsed.scheme or not parsed.netloc:
                    referrer = ''
            except Exception:
                referrer = ''

        ProfilePageView.objects.create(
            user=profile_user,
            ip_hash=hash_ip(ip),
            referrer=referrer,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:300],
        )

        return render(request, 'users/public-profile.html', {
            'profile_user': profile_user,
            'profile': profile,
            'links': links,
        })


class ProfileLinkClickView(View):
    """Track link click and redirect."""

    def get(self, request, username, link_id):
        link = get_object_or_404(
            ProfileLink,
            pk=link_id,
            user__username__iexact=username,
            is_active=True,
        )
        # Atomic click increment
        link.increment_clicks()

        # Record detailed click analytics
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ',' in ip:
            ip = ip.split(',')[0].strip()
        referrer = request.META.get('HTTP_REFERER', '')
        if referrer:
            try:
                parsed = urlparse(referrer)
                if not parsed.scheme or not parsed.netloc:
                    referrer = ''
            except Exception:
                referrer = ''

        ProfileLinkClick.objects.create(
            link=link,
            ip_hash=hash_ip(ip),
            referrer=referrer,
        )

        return redirect(link.url)


# ─── Profile Link Management Views ──────────────────────────────────────────


class ProfileLinksManageView(LoginRequiredMixin, View):
    """Manage profile links — list, usage bar, analytics summary."""
    template_name = 'users/profile-links.html'

    def get(self, request):
        links = ProfileLink.objects.filter(user=request.user)
        link_count = links.count()

        # Feature limit check
        subscription = get_user_subscription(request.user)
        link_limit = 3  # default
        if request.user.is_staff:
            link_limit = 999
        elif subscription and subscription.plan:
            link_limit = subscription.plan.get_feature_limit('profile_links', 3)

        link_percentage = min(100, int((link_count / link_limit) * 100)) if link_limit else 0

        # Analytics summary
        total_views = ProfilePageView.objects.filter(user=request.user).count()
        unique_views = ProfilePageView.objects.filter(user=request.user).values('ip_hash').distinct().count()
        total_clicks = links.aggregate(total=Sum('click_count'))['total'] or 0
        unique_clicks = ProfileLinkClick.objects.filter(link__user=request.user).values('ip_hash').distinct().count()
        ctr = round((total_clicks / total_views * 100), 1) if total_views > 0 else 0

        # Per-link unique clicks
        links_with_stats = []
        for link in links:
            uc = ProfileLinkClick.objects.filter(link=link).values('ip_hash').distinct().count()
            links_with_stats.append({'link': link, 'unique_clicks': uc})

        # Check for downgrade — excess links
        excess_links = max(0, link_count - link_limit) if link_limit else 0

        return render(request, self.template_name, {
            'links_with_stats': links_with_stats,
            'link_count': link_count,
            'link_limit': link_limit,
            'link_percentage': link_percentage,
            'total_views': total_views,
            'unique_views': unique_views,
            'total_clicks': total_clicks,
            'unique_clicks': unique_clicks,
            'ctr': ctr,
            'excess_links': excess_links,
        })


class ProfileLinkAddView(LoginRequiredMixin, View):
    """Add a new profile link."""
    template_name = 'users/profile-link-form.html'

    def _check_link_limit(self, request):
        if request.user.is_staff:
            return False, None
        current_count = ProfileLink.objects.filter(user=request.user).count()
        subscription = get_user_subscription(request.user)
        if subscription and subscription.plan:
            feature = subscription.plan.get_feature('profile_links')
            if feature:
                limit = feature.get('limit')
                if limit and current_count >= limit:
                    return True, limit
        # Fallback default limit
        if current_count >= 3:
            return True, 3
        return False, None

    def get(self, request):
        limit_reached, limit = self._check_link_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} links. Please upgrade your plan.')
            return redirect('profile_links_manage')
        form = ProfileLinkForm()
        return render(request, self.template_name, {'form': form, 'editing': False})

    def post(self, request):
        limit_reached, limit = self._check_link_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} links. Please upgrade your plan.')
            return redirect('profile_links_manage')

        form = ProfileLinkForm(request.POST)
        if form.is_valid():
            link = form.save(commit=False)
            link.user = request.user
            # Set order to be last
            last_order = ProfileLink.objects.filter(user=request.user).count()
            link.order = last_order
            link.save()
            messages.success(request, 'Link added successfully!')
            return redirect('profile_links_manage')

        return render(request, self.template_name, {'form': form, 'editing': False})


class ProfileLinkEditView(LoginRequiredMixin, View):
    """Edit an existing profile link."""
    template_name = 'users/profile-link-form.html'

    def get(self, request, pk):
        link = get_object_or_404(ProfileLink, pk=pk, user=request.user)
        form = ProfileLinkForm(instance=link)
        return render(request, self.template_name, {'form': form, 'editing': True, 'link': link})

    def post(self, request, pk):
        link = get_object_or_404(ProfileLink, pk=pk, user=request.user)
        form = ProfileLinkForm(request.POST, instance=link)
        if form.is_valid():
            form.save()
            messages.success(request, 'Link updated successfully!')
            return redirect('profile_links_manage')
        return render(request, self.template_name, {'form': form, 'editing': True, 'link': link})


class ProfileLinkDeleteView(LoginRequiredMixin, View):
    """Delete a profile link."""

    def post(self, request, pk):
        link = get_object_or_404(ProfileLink, pk=pk, user=request.user)
        link.delete()
        messages.success(request, 'Link deleted.')
        return redirect('profile_links_manage')


class ProfileLinkToggleView(LoginRequiredMixin, View):
    """Toggle a profile link's active state."""

    def post(self, request, pk):
        link = get_object_or_404(ProfileLink, pk=pk, user=request.user)
        link.is_active = not link.is_active
        link.save(update_fields=['is_active', 'updated_at'])
        state = 'enabled' if link.is_active else 'disabled'
        messages.success(request, f'Link {state}.')
        return redirect('profile_links_manage')


class ProfileLinksReorderView(LoginRequiredMixin, View):
    """AJAX endpoint to reorder profile links."""

    def post(self, request):
        try:
            data = json.loads(request.body)
            order_ids = data.get('order', [])
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        # Validate all IDs belong to this user
        user_link_ids = set(
            ProfileLink.objects.filter(user=request.user).values_list('id', flat=True)
        )
        for idx, link_id in enumerate(order_ids):
            if int(link_id) in user_link_ids:
                ProfileLink.objects.filter(pk=link_id, user=request.user).update(order=idx)

        return JsonResponse({'status': 'ok'})


class ProfileAnalyticsView(LoginRequiredMixin, View):
    """Analytics dashboard for profile views & clicks."""
    template_name = 'users/profile-analytics.html'

    def get(self, request):
        period = request.GET.get('period', '30d')
        now = timezone.now()

        if period == 'today':
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == '7d':
            since = now - timezone.timedelta(days=7)
        elif period == 'all':
            since = None
        else:  # 30d default
            period = '30d'
            since = now - timezone.timedelta(days=30)

        # Page views
        views_qs = ProfilePageView.objects.filter(user=request.user)
        if since:
            views_qs = views_qs.filter(viewed_at__gte=since)
        total_views = views_qs.count()
        unique_views = views_qs.values('ip_hash').distinct().count()

        # Links and clicks
        links = ProfileLink.objects.filter(user=request.user)
        total_clicks = links.aggregate(total=Sum('click_count'))['total'] or 0
        avg_ctr = round((total_clicks / total_views * 100), 1) if total_views > 0 else 0

        # Per-link stats
        link_stats = []
        for link in links:
            clicks_qs = ProfileLinkClick.objects.filter(link=link)
            if since:
                clicks_qs = clicks_qs.filter(clicked_at__gte=since)
            clicks = clicks_qs.count()
            unique_clicks = clicks_qs.values('ip_hash').distinct().count()
            ctr = round((clicks / total_views * 100), 1) if total_views > 0 else 0
            link_stats.append({
                'link': link,
                'clicks': clicks,
                'unique_clicks': unique_clicks,
                'ctr': ctr,
            })

        # Top referrers
        referrer_qs = views_qs.exclude(referrer='').values('referrer')
        referrer_counts = {}
        for entry in referrer_qs:
            try:
                domain = urlparse(entry['referrer']).netloc
            except Exception:
                domain = entry['referrer']
            if domain:
                referrer_counts[domain] = referrer_counts.get(domain, 0) + 1
        top_referrers = sorted(referrer_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Daily views for chart (last 30 days max)
        chart_since = now - timezone.timedelta(days=30)
        daily_views = (
            ProfilePageView.objects.filter(user=request.user, viewed_at__gte=chart_since)
            .extra({'date': "date(viewed_at)"})
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )
        chart_data = json.dumps([
            {'date': str(d['date']), 'count': d['count']}
            for d in daily_views
        ])

        return render(request, self.template_name, {
            'period': period,
            'total_views': total_views,
            'unique_views': unique_views,
            'total_clicks': total_clicks,
            'avg_ctr': avg_ctr,
            'link_stats': link_stats,
            'top_referrers': top_referrers,
            'chart_data': chart_data,
        })
