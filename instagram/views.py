import json
import logging
import requests
import urllib.parse
import base64
import hmac
import hashlib
import uuid
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from .models import InstagramAccount, InstagramAutomation, InstagramCommentEvent
from core.models import Configuration
from core.subscription_utils import check_feature_access, get_user_subscription

logger = logging.getLogger(__name__)


class IGAutomationFeatureRequiredMixin:
    """Mixin to check if user has ig_post_automation feature access"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        # Staff users bypass all checks
        if request.user.is_staff:
            return super().dispatch(request, *args, **kwargs)

        can_access, message, _ = check_feature_access(request.user, 'ig_post_automation')
        if not can_access:
            messages.error(request, 'You need to upgrade your plan to access Instagram Automation.')
            return redirect('subscription')

        return super().dispatch(request, *args, **kwargs)


class IGAccountAutomationFeatureRequiredMixin:
    """Mixin to check if user has ig_account_automation feature (Creator plan)"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        # Staff users bypass all checks
        if request.user.is_staff:
            return super().dispatch(request, *args, **kwargs)

        can_access, message, _ = check_feature_access(request.user, 'ig_account_automation')
        if not can_access:
            messages.error(request, 'Account-level automation is available on the Creator plan. Please upgrade.')
            return redirect('subscription')

        return super().dispatch(request, *args, **kwargs)


class InstagramConnectView(LoginRequiredMixin, View):
    """Display Instagram connection status"""

    def get(self, request):
        instagram_account = None
        instagram_connected = False

        if hasattr(request.user, 'instagram_account'):
            instagram_account = request.user.instagram_account
            instagram_connected = instagram_account.is_connected

        context = {
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
        }
        return render(request, 'instagram/connect.html', context)


class InstagramOAuthRedirectView(LoginRequiredMixin, View):
    """Redirect user to Instagram OAuth"""

    def post(self, request):
        app_root_url = Configuration.get_value('app_root_url', '')
        instagram_app_id = Configuration.get_value('instagram_app_id', '')

        if not app_root_url or not instagram_app_id:
            messages.error(request, 'Instagram app not configured. Contact admin.')
            return redirect('instagram_connect')

        redirect_uri = f"{app_root_url.rstrip('/')}/instagram/callback/"

        scopes = [
            "instagram_business_basic",
            "instagram_business_content_publish",
            "instagram_business_manage_comments",
            "instagram_business_manage_messages",
            "instagram_business_manage_insights",
        ]

        params = {
            "client_id": instagram_app_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "state": str(request.user.id),
        }

        oauth_url = (
            "https://www.instagram.com/oauth/authorize?"
            + urllib.parse.urlencode(params)
        )
        return redirect(oauth_url)


class InstagramCallbackView(LoginRequiredMixin, View):
    """Handle Instagram OAuth callback"""

    def subscribe_to_webhook_events(self, ig_user_id, access_token, user):
        """Subscribe to Instagram webhook events (comments and messages)"""
        try:
            url = f"https://graph.instagram.com/v21.0/{ig_user_id}/subscribed_apps"

            params = {
                "subscribed_fields": "comments,messages",
                "access_token": access_token,
            }

            logger.info(f"Subscribing to webhook events for Instagram account: {ig_user_id}")

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
                # Update the webhook_subscribed field in instagram_data
                if hasattr(user, 'instagram_account'):
                    instagram_account = user.instagram_account
                    if instagram_account.instagram_data:
                        instagram_account.instagram_data["webhook_subscribed"] = True
                        instagram_account.save(update_fields=["instagram_data"])

                logger.info(f"Successfully subscribed to webhook events for {ig_user_id}")
                return True
            else:
                error_message = response_data.get("error", {}).get("message", "Unknown error")
                logger.error(f"Failed to subscribe to webhook events: {error_message}")
                return False

        except requests.RequestException as e:
            logger.error(f"Request error during webhook subscription: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error subscribing to webhook events: {str(e)}")
            return False

    def get(self, request):
        state = request.GET.get("state")
        code = request.GET.get("code")
        error_description = request.GET.get("error_description")
        error_reason = request.GET.get("error_reason")

        if error_description or error_reason:
            messages.error(request, f"Instagram connection failed: {error_reason}")
            return redirect("instagram_connect")

        if not code or not state:
            messages.error(request, "Invalid callback parameters.")
            return redirect("instagram_connect")

        # Verify state matches user
        if state != str(request.user.id):
            messages.error(request, "Invalid state parameter.")
            return redirect("instagram_connect")

        # Load configuration
        app_root_url = Configuration.get_value('app_root_url', '')
        instagram_app_id = Configuration.get_value('instagram_app_id', '')
        instagram_app_secret = Configuration.get_value('instagram_app_secret', '')

        if not all([app_root_url, instagram_app_id, instagram_app_secret]):
            messages.error(request, "Instagram app not configured properly.")
            return redirect("instagram_connect")

        redirect_uri = f"{app_root_url.rstrip('/')}/instagram/callback/"

        try:
            # Step 1: Exchange code for short-lived token
            token_response = requests.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": instagram_app_id,
                    "client_secret": instagram_app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=10,
            )
            token_data = token_response.json()

            if not token_response.ok or "access_token" not in token_data:
                raise ValueError(
                    token_data.get("error_message")
                    or token_data.get("error", "Invalid token response")
                )

            short_lived_token = token_data["access_token"]

            # Step 2: Exchange for long-lived token
            long_lived_response = requests.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": instagram_app_secret,
                    "access_token": short_lived_token,
                },
                timeout=30,
            )
            long_lived_data = long_lived_response.json()

            if not long_lived_response.ok or "access_token" not in long_lived_data:
                raise ValueError(
                    long_lived_data.get("error_message")
                    or long_lived_data.get("error", "Failed to get long-lived token")
                )

            access_token = long_lived_data["access_token"]
            expires_in = long_lived_data.get("expires_in", 5184000)  # 60 days
            token_expires_at = timezone.now() + timedelta(seconds=expires_in)

            # Step 3: Fetch user details with all available fields
            # Request comprehensive fields including those available with insights permission
            user_info_response = requests.get(
                "https://graph.instagram.com/v21.0/me",
                params={
                    "fields": "id,username,account_type,user_id,name,profile_picture_url,followers_count,follows_count,media_count",
                    "access_token": access_token,
                },
                timeout=10,
            )

            if not user_info_response.ok:
                raise ValueError(
                    f"Failed to fetch Instagram user info: {user_info_response.text}"
                )

            user_info = user_info_response.json()
            logger.info(f"Instagram /me response: {user_info}")

            # The ID from /me endpoint with instagram_business_* scopes
            # is the Instagram Professional Account ID (same as webhook entry.id)
            ig_account_id = str(user_info.get("id", ""))

            # Some accounts might have a separate user_id field
            ig_user_id = str(user_info.get("user_id", "")) or ig_account_id

            # Also try to fetch from the account endpoint directly for additional info
            try:
                account_info_response = requests.get(
                    f"https://graph.instagram.com/v21.0/{ig_account_id}",
                    params={
                        "fields": "id,username,account_type,ig_id",
                        "access_token": access_token,
                    },
                    timeout=10,
                )
                if account_info_response.ok:
                    account_info = account_info_response.json()
                    logger.info(f"Instagram account info response: {account_info}")
                    # ig_id might be a different ID format
                    if account_info.get("ig_id"):
                        ig_user_id = str(account_info.get("ig_id"))
            except Exception as e:
                logger.warning(f"Could not fetch additional account info: {e}")

            # Step 4: Save or update InstagramAccount
            # Store the main ID which should match webhook entry.id
            business_account_id = ig_account_id

            _, created = InstagramAccount.objects.update_or_create(
                user=request.user,
                defaults={
                    "instagram_user_id": business_account_id,
                    "username": user_info.get("username", ""),
                    "access_token": access_token,
                    "token_expires_at": token_expires_at,
                    "is_active": True,
                    "instagram_data": {
                        "user_info": user_info,
                        "account_id": ig_account_id,  # Main ID from /me
                        "user_id": ig_user_id,  # User ID or ig_id if different
                        "ig_id": ig_user_id,  # Explicit ig_id for webhook matching
                        "business_account_id": business_account_id,  # For webhook matching
                        "account_type": user_info.get("account_type", ""),
                        "connected_at": str(timezone.now()),
                    },
                },
            )

            logger.info(
                f"Instagram connected for user {request.user.id}: "
                f"account_id={ig_account_id}, user_id={ig_user_id}, "
                f"username={user_info.get('username')}, account_type={user_info.get('account_type')}"
            )

            # Step 5: Auto-subscribe to webhook events (comments and messages)
            subscription_success = self.subscribe_to_webhook_events(
                ig_account_id, access_token, request.user
            )

            action = "connected" if created else "reconnected"
            if subscription_success:
                messages.success(
                    request,
                    f"Instagram account @{user_info.get('username')} {action} "
                    f"and subscribed to comments & messages!"
                )
            else:
                messages.warning(
                    request,
                    f"Instagram account @{user_info.get('username')} {action}, "
                    f"but webhook subscription failed. You can retry from settings."
                )

        except requests.RequestException as e:
            messages.error(request, f"Network error connecting to Instagram: {str(e)}")
        except ValueError as e:
            messages.error(request, f"Instagram API error: {str(e)}")
        except Exception as e:
            messages.error(request, f"Unexpected error: {str(e)}")

        return redirect("instagram_connect")


class InstagramDisconnectView(LoginRequiredMixin, View):
    """Disconnect Instagram account"""

    def post(self, request):
        try:
            if hasattr(request.user, 'instagram_account'):
                instagram_account = request.user.instagram_account
                instagram_account.access_token = None
                instagram_account.is_active = False
                instagram_account.save()
                messages.success(request, "Instagram account disconnected.")
            return redirect("instagram_connect")
        except Exception as e:
            messages.error(request, f"Error disconnecting: {str(e)}")
            return redirect("instagram_connect")


class InstagramWebhookSubscribeView(LoginRequiredMixin, View):
    """Manually subscribe to Instagram webhook events"""

    def post(self, request):
        try:
            if not hasattr(request.user, 'instagram_account'):
                return JsonResponse({
                    'success': False,
                    'error': 'No Instagram account connected'
                }, status=400)

            instagram_account = request.user.instagram_account

            if not instagram_account.is_connected:
                return JsonResponse({
                    'success': False,
                    'error': 'Instagram account not active'
                }, status=400)

            ig_user_id = instagram_account.instagram_user_id
            access_token = instagram_account.access_token

            if not ig_user_id or not access_token:
                return JsonResponse({
                    'success': False,
                    'error': 'Missing account credentials'
                }, status=400)

            # Subscribe to webhook events
            url = f"https://graph.instagram.com/v21.0/{ig_user_id}/subscribed_apps"

            params = {
                "subscribed_fields": "comments,messages",
                "access_token": access_token,
            }

            logger.info(f"Manual subscription to webhook events for: {ig_user_id}")

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
                # Update the webhook_subscribed field
                if instagram_account.instagram_data:
                    instagram_account.instagram_data["webhook_subscribed"] = True
                else:
                    instagram_account.instagram_data = {"webhook_subscribed": True}
                instagram_account.save(update_fields=["instagram_data"])

                return JsonResponse({
                    'success': True,
                    'message': 'Successfully subscribed to comments & messages'
                })
            else:
                error_message = response_data.get("error", {}).get("message", "Unknown error")
                logger.error(f"Failed to subscribe: {error_message}")
                return JsonResponse({
                    'success': False,
                    'error': error_message
                }, status=400)

        except requests.RequestException as e:
            logger.error(f"Request error during subscription: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Network error: {str(e)}'
            }, status=500)
        except Exception as e:
            logger.error(f"Error subscribing to webhook events: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)


class InstagramPostPageView(LoginRequiredMixin, View):
    """Page to post video to Instagram with caption"""
    template_name = 'instagram/post.html'

    def get(self, request):
        video_url = request.GET.get('video_url', '')
        video_title = request.GET.get('title', 'Quiz Video')
        return_url = request.GET.get('return_url', '')

        if not video_url:
            messages.error(request, 'No video URL provided.')
            return redirect('dashboard')

        # Check Instagram connection
        if not hasattr(request.user, 'instagram_account') or not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        context = {
            'video_url': video_url,
            'video_title': video_title,
            'return_url': return_url,
            'instagram_username': request.user.instagram_account.username,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        video_url = request.POST.get('video_url', '')
        caption = request.POST.get('caption', '')
        return_url = request.POST.get('return_url', '')

        if not video_url:
            messages.error(request, 'No video URL provided.')
            return redirect('dashboard')

        # Check Instagram connection
        if not hasattr(request.user, 'instagram_account'):
            messages.error(request, 'Instagram not connected.')
            return redirect('instagram_connect')

        ig_account = request.user.instagram_account
        if not ig_account.is_connected:
            messages.error(request, 'Instagram token expired. Please reconnect.')
            return redirect('instagram_connect')

        access_token = ig_account.access_token
        ig_user_id = ig_account.instagram_user_id

        try:
            import time

            # Step 1: Create media container for Reel
            container_response = requests.post(
                f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "access_token": access_token,
                },
                timeout=30,
            )
            container_data = container_response.json()

            if "id" not in container_data:
                error_msg = container_data.get("error", {}).get("message", "Failed to create media")
                messages.error(request, f'Instagram error: {error_msg}')
                return redirect(return_url or 'dashboard')

            container_id = container_data["id"]

            # Step 2: Wait for video processing to complete
            max_attempts = 30  # Max 5 minutes
            for attempt in range(max_attempts):
                status_response = requests.get(
                    f"https://graph.instagram.com/v21.0/{container_id}",
                    params={
                        "fields": "status_code,status",
                        "access_token": access_token,
                    },
                    timeout=10,
                )
                status_data = status_response.json()
                status_code = status_data.get("status_code")

                if status_code == "FINISHED":
                    break
                elif status_code == "ERROR":
                    error_status = status_data.get("status", "Unknown processing error")
                    messages.error(request, f'Video processing failed: {error_status}')
                    return redirect(return_url or 'dashboard')
                else:
                    time.sleep(10)
            else:
                messages.error(request, 'Video processing timeout. Please try again.')
                return redirect(return_url or 'dashboard')

            # Step 3: Publish the container
            publish_response = requests.post(
                f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
                data={
                    "creation_id": container_id,
                    "access_token": access_token,
                },
                timeout=60,
            )
            publish_data = publish_response.json()

            if "id" not in publish_data:
                error_msg = publish_data.get("error", {}).get("message", "Failed to publish")
                messages.error(request, f'Instagram error: {error_msg}')
                return redirect(return_url or 'dashboard')

            messages.success(request, 'Video posted to Instagram Reels successfully!')
            return redirect(return_url or 'dashboard')

        except Exception as e:
            messages.error(request, f'Error posting to Instagram: {str(e)}')
            return redirect(return_url or 'dashboard')


# =============================================================================
# Instagram Automation Views
# =============================================================================

class InstagramPostsAPIView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """API endpoint to fetch user's Instagram posts for browsing"""

    def get(self, request):
        # Check if Instagram is connected
        if not hasattr(request.user, 'instagram_account'):
            return JsonResponse({
                'success': False,
                'error': 'Instagram account not connected.'
            })

        instagram_account = request.user.instagram_account
        if not instagram_account.is_connected:
            return JsonResponse({
                'success': False,
                'error': 'Instagram token expired. Please reconnect.'
            })

        access_token = instagram_account.access_token
        ig_user_id = instagram_account.instagram_user_id

        try:
            # Fetch user's media posts
            media_url = f"https://graph.instagram.com/v21.0/{ig_user_id}/media"
            params = {
                'fields': 'id,media_type,media_url,thumbnail_url,timestamp,caption,permalink',
                'access_token': access_token,
                'limit': 50
            }

            response = requests.get(media_url, params=params, timeout=30)
            data = response.json()

            if 'error' in data:
                return JsonResponse({
                    'success': False,
                    'error': f"Instagram API error: {data['error'].get('message', 'Unknown error')}"
                })

            posts = data.get('data', [])

            return JsonResponse({
                'success': True,
                'posts': posts,
                'count': len(posts)
            })

        except requests.RequestException as e:
            return JsonResponse({
                'success': False,
                'error': f'Network error fetching posts: {str(e)}'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Failed to fetch Instagram posts: {str(e)}'
            })


class AutomationLandingView(View):
    """Public landing page for Instagram automation feature"""
    template_name = 'instagram/automation_landing.html'

    def get(self, request):
        context = {
            'has_feature_access': False,
        }

        # Check if user has feature access
        if request.user.is_authenticated:
            can_access, _, _ = check_feature_access(request.user, 'ig_post_automation')
            context['has_feature_access'] = can_access

        return render(request, self.template_name, context)


class AutomationListView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """List all Instagram automations for the user"""
    template_name = 'instagram/automation_list.html'

    def get(self, request):
        # Check if Instagram is connected
        instagram_connected = False
        instagram_account = None
        if hasattr(request.user, 'instagram_account'):
            instagram_account = request.user.instagram_account
            instagram_connected = instagram_account.is_connected

        # Get user's automations
        automations = InstagramAutomation.objects.filter(user=request.user)
        automation_count = automations.count()

        # Get automation limit from subscription
        automation_limit = None
        can_create_more = True
        can_use_account_automation = request.user.is_staff

        if not request.user.is_staff:
            subscription = get_user_subscription(request.user)
            if subscription and subscription.plan:
                feature = subscription.plan.get_feature('ig_post_automation')
                if feature:
                    automation_limit = feature.get('limit')
                    if automation_limit:
                        can_create_more = automation_count < automation_limit
                # Check if user can use account-level automation
                can_use_account_automation = subscription.plan.has_feature('ig_account_automation')

        # Get recent comment events
        recent_events = InstagramCommentEvent.objects.filter(
            user=request.user
        ).select_related('automation')[:20]

        context = {
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
            'automations': automations,
            'automation_count': automation_count,
            'automation_limit': automation_limit,
            'can_create_more': can_create_more,
            'can_use_account_automation': can_use_account_automation,
            'recent_events': recent_events,
        }
        return render(request, self.template_name, context)


class AutomationCreateView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Create a new Instagram automation"""
    template_name = 'instagram/automation_form.html'

    def _check_automation_limit(self, request):
        """Check if user has reached their automation limit. Returns (limit_reached, limit_count)"""
        if request.user.is_staff:
            return False, None

        current_count = InstagramAutomation.objects.filter(user=request.user).count()
        subscription = get_user_subscription(request.user)
        if subscription and subscription.plan:
            feature = subscription.plan.get_feature('ig_post_automation')
            if feature:
                limit = feature.get('limit')
                if limit and current_count >= limit:
                    return True, limit
        return False, None

    def get(self, request):
        # Check if Instagram is connected
        if not hasattr(request.user, 'instagram_account') or \
           not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        # Check automation limit
        limit_reached, limit = self._check_automation_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} automations. Please upgrade your plan for more.')
            return redirect('instagram_automation_list')

        context = {
            'editing': False,
            'automation': None,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        # Check if Instagram is connected
        if not hasattr(request.user, 'instagram_account') or \
           not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        # Check automation limit
        limit_reached, limit = self._check_automation_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} automations. Please upgrade your plan for more.')
            return redirect('instagram_automation_list')

        title = request.POST.get('title', '').strip()
        instagram_post_id = request.POST.get('instagram_post_id', '').strip()
        keywords = request.POST.get('keywords', '').strip()

        # Get multiple replies/DMs as lists (filter out empty values)
        comment_replies = [r.strip() for r in request.POST.getlist('comment_replies[]') if r.strip()]
        followup_dms = [d.strip() for d in request.POST.getlist('followup_dms[]') if d.strip()]

        # Validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')
        if not instagram_post_id:
            errors.append('Please select an Instagram post.')
        if not comment_replies:
            errors.append('At least one comment reply is required.')
        if len(comment_replies) > 5:
            errors.append('Maximum 5 comment replies allowed.')
        if len(followup_dms) > 5:
            errors.append('Maximum 5 follow-up DMs allowed.')

        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'editing': False,
                'automation': {
                    'title': title,
                    'instagram_post_id': instagram_post_id,
                    'keywords': keywords,
                    'comment_replies': comment_replies,
                    'followup_dms': followup_dms,
                },
            }
            return render(request, self.template_name, context)

        # Create automation
        InstagramAutomation.objects.create(
            user=request.user,
            title=title,
            instagram_post_id=instagram_post_id,
            keywords=keywords,
            comment_replies=comment_replies,
            followup_dms=followup_dms,
        )

        messages.success(request, f'Automation "{title}" created successfully!')
        return redirect('instagram_automation_list')


class AutomationEditView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Edit an existing Instagram automation"""
    template_name = 'instagram/automation_form.html'

    def get(self, request, pk):
        automation = get_object_or_404(
            InstagramAutomation, pk=pk, user=request.user
        )

        context = {
            'editing': True,
            'automation': automation,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        automation = get_object_or_404(
            InstagramAutomation, pk=pk, user=request.user
        )

        title = request.POST.get('title', '').strip()
        instagram_post_id = request.POST.get('instagram_post_id', '').strip()
        keywords = request.POST.get('keywords', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        # Get multiple replies/DMs as lists (filter out empty values)
        comment_replies = [r.strip() for r in request.POST.getlist('comment_replies[]') if r.strip()]
        followup_dms = [d.strip() for d in request.POST.getlist('followup_dms[]') if d.strip()]

        # Validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')
        if not instagram_post_id:
            errors.append('Please select an Instagram post.')
        if not comment_replies:
            errors.append('At least one comment reply is required.')
        if len(comment_replies) > 5:
            errors.append('Maximum 5 comment replies allowed.')
        if len(followup_dms) > 5:
            errors.append('Maximum 5 follow-up DMs allowed.')

        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'editing': True,
                'automation': automation,
            }
            return render(request, self.template_name, context)

        # Update automation
        automation.title = title
        automation.instagram_post_id = instagram_post_id
        automation.keywords = keywords
        automation.comment_replies = comment_replies
        automation.followup_dms = followup_dms
        automation.is_active = is_active
        automation.save()

        messages.success(request, f'Automation "{title}" updated successfully!')
        return redirect('instagram_automation_list')


class AutomationDeleteView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Delete an Instagram automation"""

    def post(self, request, pk):
        automation = get_object_or_404(
            InstagramAutomation, pk=pk, user=request.user
        )
        title = automation.title
        automation.delete()
        messages.success(request, f'Automation "{title}" deleted.')
        return redirect('instagram_automation_list')


class AccountAutomationView(IGAccountAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Configure account-level automation settings (Creator plan feature)"""
    template_name = 'instagram/automation_account.html'

    def get(self, request):
        # Check if Instagram is connected
        if not hasattr(request.user, 'instagram_account'):
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        instagram_account = request.user.instagram_account
        if not instagram_account.is_connected:
            messages.error(request, 'Please reconnect your Instagram account.')
            return redirect('instagram_connect')

        context = {
            'instagram_account': instagram_account,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        if not hasattr(request.user, 'instagram_account'):
            messages.error(request, 'Instagram account not found.')
            return redirect('instagram_connect')

        instagram_account = request.user.instagram_account

        account_automation_enabled = request.POST.get('account_automation_enabled') == 'on'

        # Get multiple replies/DMs as lists (filter out empty values)
        account_comment_replies = [r.strip() for r in request.POST.getlist('account_comment_replies[]') if r.strip()]
        account_followup_dms = [d.strip() for d in request.POST.getlist('account_followup_dms[]') if d.strip()]

        # Validate max 5 items
        if len(account_comment_replies) > 5:
            account_comment_replies = account_comment_replies[:5]
        if len(account_followup_dms) > 5:
            account_followup_dms = account_followup_dms[:5]

        # Require at least one reply when enabling
        if account_automation_enabled and not account_comment_replies:
            messages.error(request, 'Please add at least one comment reply to enable automation.')
            context = {'instagram_account': instagram_account}
            return render(request, self.template_name, context)

        # Update account settings
        instagram_account.account_automation_enabled = account_automation_enabled
        instagram_account.account_comment_replies = account_comment_replies
        instagram_account.account_followup_dms = account_followup_dms
        instagram_account.save()

        messages.success(request, 'Account automation settings saved!')
        return redirect('instagram_automation_list')


# =============================================================================
# Instagram Webhook Handler
# =============================================================================

@method_decorator(csrf_exempt, name='dispatch')
class InstagramWebhookView(View):
    """Handle Instagram webhook events for comment automation"""

    def get(self, request):
        """Verify webhook subscription (challenge-response)"""
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')

        verify_token = Configuration.get_value('instagram_webhook_verify_token', '')

        if mode == 'subscribe' and token == verify_token:
            logger.info("Instagram webhook verification successful")
            return HttpResponse(challenge, content_type='text/plain')

        logger.warning(f"Instagram webhook verification failed: mode={mode}")
        return HttpResponse('Forbidden', status=403)

    def post(self, request):
        """Process incoming webhook events"""
        try:
            payload = json.loads(request.body)
            logger.info(f"Instagram webhook received full payload: {json.dumps(payload)}")

            # Process each entry
            for entry in payload.get('entry', []):
                # The entry 'id' is the Instagram Business Account ID
                ig_business_account_id = str(entry.get('id', ''))
                logger.info(
                    f"Processing webhook entry: id={ig_business_account_id}, "
                    f"time={entry.get('time')}, changes_count={len(entry.get('changes', []))}"
                )

                # Handle comment changes
                for change in entry.get('changes', []):
                    if change.get('field') == 'comments':
                        self.handle_comment(change.get('value', {}), ig_business_account_id)

            return JsonResponse({'status': 'ok'})

        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            return JsonResponse({'status': 'error'}, status=500)

    def handle_comment(self, comment_data, ig_business_account_id):
        """Process a new comment and trigger automation"""
        comment_id = comment_data.get('id')
        post_id = comment_data.get('media', {}).get('id', '')
        comment_text = comment_data.get('text', '')
        commenter_id = comment_data.get('from', {}).get('id', '')
        commenter_username = comment_data.get('from', {}).get('username', '')
        parent_id = comment_data.get('parent_id', '')

        # Skip if this is a reply to another comment (not a top-level comment)
        if parent_id:
            logger.info(f"Skipping comment {comment_id} - it's a reply to {parent_id}")
            return

        if not comment_id:
            logger.warning("Comment event missing comment_id")
            return

        # Simple deduplication check first
        if InstagramCommentEvent.objects.filter(comment_id=comment_id).exists():
            logger.info(f"Comment {comment_id} already processed, skipping")
            return

        # Create event record immediately for deduplication
        from django.db import IntegrityError
        try:
            event = InstagramCommentEvent.objects.create(
                comment_id=comment_id,
                post_id=post_id,
                commenter_username=commenter_username,
                commenter_id=commenter_id,
                comment_text=comment_text,
                status='processing'
            )
        except IntegrityError:
            logger.info(f"Comment {comment_id} already being processed (race condition), skipping")
            return

        # Find the Instagram account this comment belongs to
        logger.info(f"Looking for Instagram account with webhook ID: {ig_business_account_id}")

        instagram_account = None

        # Method 1: Direct match on instagram_user_id
        try:
            instagram_account = InstagramAccount.objects.get(
                instagram_user_id=ig_business_account_id,
                is_active=True
            )
            logger.info(f"Found account by instagram_user_id: {instagram_account.username}")
        except InstagramAccount.DoesNotExist:
            pass

        # Method 2: Match by account_id in instagram_data
        if not instagram_account:
            try:
                instagram_account = InstagramAccount.objects.get(
                    instagram_data__account_id=ig_business_account_id,
                    is_active=True
                )
                logger.info(f"Found account by instagram_data.account_id: {instagram_account.username}")
            except InstagramAccount.DoesNotExist:
                pass

        # Method 3: Match by business_account_id in instagram_data
        if not instagram_account:
            try:
                instagram_account = InstagramAccount.objects.get(
                    instagram_data__business_account_id=ig_business_account_id,
                    is_active=True
                )
                logger.info(f"Found account by instagram_data.business_account_id: {instagram_account.username}")
            except InstagramAccount.DoesNotExist:
                pass

        # Method 4: Match by user_id in instagram_data
        if not instagram_account:
            try:
                instagram_account = InstagramAccount.objects.get(
                    instagram_data__user_id=ig_business_account_id,
                    is_active=True
                )
                logger.info(f"Found account by instagram_data.user_id: {instagram_account.username}")
            except InstagramAccount.DoesNotExist:
                pass

        # Method 5: Match by ig_id in instagram_data
        if not instagram_account:
            try:
                instagram_account = InstagramAccount.objects.get(
                    instagram_data__ig_id=ig_business_account_id,
                    is_active=True
                )
                logger.info(f"Found account by instagram_data.ig_id: {instagram_account.username}")
            except InstagramAccount.DoesNotExist:
                pass

        # If still no match, log debug info and return
        if not instagram_account:
            all_accounts = InstagramAccount.objects.filter(is_active=True)
            debug_info = []
            for acc in all_accounts:
                debug_info.append({
                    'user_id': acc.instagram_user_id,
                    'username': acc.username,
                    'data': acc.instagram_data
                })
            logger.warning(
                f"No active Instagram account found for webhook ID: {ig_business_account_id}. "
                f"Active accounts: {debug_info}"
            )
            # Mark event as failed since we couldn't find the account
            event.status = 'failed'
            event.error_message = f'No matching Instagram account for ID: {ig_business_account_id}'
            event.save()
            return

        user = instagram_account.user

        # Skip comments from the account itself (our own replies)
        if commenter_id == ig_business_account_id or commenter_id == instagram_account.instagram_user_id:
            logger.info(f"Skipping comment {comment_id} - from account owner")
            event.status = 'skipped'
            event.error_message = 'Comment from account owner'
            event.save()
            return

        # Update event with user association
        event.user = user
        event.status = 'received'
        event.save()

        # Find matching automation
        automation = None
        comment_reply = None
        followup_dm = None

        # First, try to find post-level automation
        automations = InstagramAutomation.objects.filter(
            user=user,
            is_active=True
        )

        for auto in automations:
            # Check if post ID matches (if specified)
            if auto.instagram_post_id and auto.instagram_post_id != post_id:
                continue

            # Check if keywords match
            if auto.matches_comment(comment_text):
                automation = auto
                # Randomly select from available replies/DMs
                comment_reply = auto.get_random_comment_reply()
                followup_dm = auto.get_random_followup_dm()  # Returns None if empty list
                break

        # If no post-level automation matched, check account-level
        if not automation and instagram_account.account_automation_enabled:
            # Randomly select from account-level replies/DMs
            comment_reply = instagram_account.get_random_comment_reply()
            followup_dm = instagram_account.get_random_followup_dm()  # Returns None if empty list

        # If no automation configured, skip
        if not comment_reply:
            event.status = 'skipped'
            event.error_message = 'No matching automation found'
            event.save()
            logger.info(f"No automation for comment {comment_id}")
            return

        # Update event with automation info
        event.automation = automation
        event.reply_text = comment_reply
        event.dm_text = followup_dm
        event.status = 'processed'
        event.save()

        # Send comment reply
        try:
            self.reply_to_comment(
                comment_id=comment_id,
                message=comment_reply,
                access_token=instagram_account.access_token
            )
            event.comment_replied = True
            event.status = 'replied'
            event.save()
            logger.info(f"Replied to comment {comment_id}")
        except Exception as e:
            logger.error(f"Failed to reply to comment {comment_id}: {str(e)}")
            event.error_message = f"Comment reply failed: {str(e)}"
            event.status = 'failed'
            event.save()
            return

        # Send follow-up DM
        if followup_dm:
            # For account-level automation (automation is None), check if we've already
            # sent a DM to this commenter before - only send once per user
            if automation is None:
                already_sent = InstagramCommentEvent.objects.filter(
                    user=user,
                    commenter_id=commenter_id,
                    automation__isnull=True,  # Account-level automation only
                    dm_sent=True
                ).exclude(pk=event.pk).exists()

                if already_sent:
                    logger.info(f"Skipping account-level DM for comment {comment_id} - already sent to commenter {commenter_id}")
                    event.status = 'completed'
                    event.error_message = 'Account-level DM already sent to this user'
                    event.save()
                    return

            try:
                self.send_dm_to_commenter(
                    comment_id=comment_id,
                    message=followup_dm,
                    ig_business_account_id=instagram_account.instagram_user_id,
                    access_token=instagram_account.access_token
                )
                event.dm_sent = True
                event.status = 'completed'
                event.save()
                logger.info(f"DM sent for comment {comment_id}")
            except Exception as e:
                logger.error(f"Failed to send DM for comment {comment_id}: {str(e)}")
                event.error_message = f"DM failed: {str(e)}"
                event.save()

    def reply_to_comment(self, comment_id, message, access_token):
        """Reply to an Instagram comment"""
        url = f"https://graph.instagram.com/v21.0/{comment_id}/replies"
        response = requests.post(
            url,
            data={
                'message': message,
                'access_token': access_token
            },
            timeout=30
        )

        if not response.ok:
            error = response.json().get('error', {}).get('message', response.text)
            raise Exception(error)

        return response.json()

    def send_dm_to_commenter(self, comment_id, message, ig_business_account_id, access_token):
        """Send a DM to the person who commented using comment_id as reference"""
        url = f"https://graph.instagram.com/v21.0/{ig_business_account_id}/messages"

        # Instagram requires using comment_id to identify recipient for DM
        payload = {
            'recipient': {'comment_id': comment_id},
            'message': {'text': message},
        }

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if not response.ok:
            error = response.json().get('error', {}).get('message', response.text)
            raise Exception(error)

        return response.json()


# =============================================================================
# Facebook/Instagram App Callback Endpoints (Required for App Review)
# =============================================================================

def parse_signed_request(signed_request, app_secret):
    """Parse and verify a signed_request from Facebook."""
    try:
        encoded_sig, payload = signed_request.split('.', 1)

        # Decode signature
        sig = base64.urlsafe_b64decode(encoded_sig + '==')

        # Decode payload
        data = json.loads(base64.urlsafe_b64decode(payload + '=='))

        # Verify signature
        expected_sig = hmac.new(
            app_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).digest()

        if hmac.compare_digest(sig, expected_sig):
            return data
        return None
    except Exception as e:
        logger.error(f"Error parsing signed_request: {e}")
        return None


@method_decorator(csrf_exempt, name='dispatch')
class DataDeletionCallbackView(View):
    """
    Handle Facebook/Instagram Data Deletion Requests.
    URL to configure in Facebook App: {your_domain}/instagram/data-deletion/
    """

    def post(self, request):
        try:
            signed_request = request.POST.get('signed_request', '')

            if not signed_request:
                return JsonResponse({'error': 'Missing signed_request'}, status=400)

            app_secret = Configuration.get_value('instagram_app_secret', '')

            if not app_secret:
                logger.error("Instagram app secret not configured for data deletion")
                return JsonResponse({'error': 'App not configured'}, status=500)

            data = parse_signed_request(signed_request, app_secret)

            if not data:
                return JsonResponse({'error': 'Invalid signed_request'}, status=400)

            user_id = data.get('user_id', '')
            logger.info(f"Data deletion request received for user_id: {user_id}")

            # Delete user's Instagram data if it exists
            if user_id:
                try:
                    instagram_account = InstagramAccount.objects.filter(
                        instagram_user_id=user_id
                    ).first()

                    if instagram_account:
                        InstagramAutomation.objects.filter(
                            user=instagram_account.user
                        ).delete()
                        InstagramCommentEvent.objects.filter(
                            user=instagram_account.user
                        ).delete()
                        instagram_account.delete()
                        logger.info(f"Deleted Instagram data for user_id: {user_id}")
                except Exception as e:
                    logger.error(f"Error deleting data for user_id {user_id}: {e}")

            # Generate confirmation code
            confirmation_code = str(uuid.uuid4())[:8].upper()

            app_root_url = Configuration.get_value('app_root_url', 'https://example.com')

            return JsonResponse({
                'url': f'{app_root_url}/privacy/data-deletion-status/?code={confirmation_code}',
                'confirmation_code': confirmation_code
            })

        except Exception as e:
            logger.error(f"Data deletion callback error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class DeauthorizationCallbackView(View):
    """
    Handle Facebook/Instagram Deauthorization Callbacks.
    URL to configure in Facebook App: {your_domain}/instagram/deauthorize/
    """

    def post(self, request):
        try:
            signed_request = request.POST.get('signed_request', '')

            if not signed_request:
                return JsonResponse({'error': 'Missing signed_request'}, status=400)

            app_secret = Configuration.get_value('instagram_app_secret', '')

            if not app_secret:
                logger.error("Instagram app secret not configured for deauthorization")
                return JsonResponse({'error': 'App not configured'}, status=500)

            data = parse_signed_request(signed_request, app_secret)

            if not data:
                return JsonResponse({'error': 'Invalid signed_request'}, status=400)

            user_id = data.get('user_id', '')
            logger.info(f"Deauthorization request received for user_id: {user_id}")

            # Deactivate user's Instagram connection
            if user_id:
                try:
                    instagram_account = InstagramAccount.objects.filter(
                        instagram_user_id=user_id
                    ).first()

                    if instagram_account:
                        instagram_account.access_token = None
                        instagram_account.is_active = False
                        instagram_account.save()
                        logger.info(f"Deauthorized Instagram account for user_id: {user_id}")
                except Exception as e:
                    logger.error(f"Error deauthorizing user_id {user_id}: {e}")

            return JsonResponse({'success': True})

        except Exception as e:
            logger.error(f"Deauthorization callback error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)
