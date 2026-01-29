#pylint: disable=all
import copy
import json
import logging
import requests
import urllib.parse
import base64
import hmac
import hashlib
import uuid
import csv
from datetime import timedelta
from django.db import models, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from .models import (
    InstagramAccount, DMFlow, FlowNode, QuickReplyOption,
    FlowSession, FlowExecutionLog, CollectedLead, FlowTemplate,
    APICallLog, QueuedFlowTrigger
)
from .flow_engine import FlowEngine, find_matching_flow, find_session_for_message, parse_quick_reply_payload
from .instagram_api import get_api_client_for_account, InstagramAPIError
from core.models import Configuration
from core.subscription_utils import check_feature_access, get_user_subscription

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Access Mixins
# =============================================================================

class IGFlowBuilderFeatureMixin:
    """Mixin to check if user has ig_flow_builder feature access"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        # Staff users bypass all checks
        if request.user.is_staff:
            return super().dispatch(request, *args, **kwargs)

        can_access, message, _ = check_feature_access(request.user, 'ig_flow_builder')
        if not can_access:
            messages.error(request, 'You need to upgrade your plan to access the DM Flow Builder.')
            return redirect('subscription')

        return super().dispatch(request, *args, **kwargs)


# =============================================================================
# Instagram Connection Views
# =============================================================================

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
                "subscribed_fields": "comments,messages,messaging_postbacks",
                "access_token": access_token,
            }

            logger.info(f"Subscribing to webhook events for Instagram account: {ig_user_id}")

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
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

        if state != str(request.user.id):
            messages.error(request, "Invalid state parameter.")
            return redirect("instagram_connect")

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
            expires_in = long_lived_data.get("expires_in", 5184000)
            token_expires_at = timezone.now() + timedelta(seconds=expires_in)

            # Step 3: Fetch user details
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

            ig_account_id = str(user_info.get("id", ""))
            ig_user_id = str(user_info.get("user_id", "")) or ig_account_id

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
                    if account_info.get("ig_id"):
                        ig_user_id = str(account_info.get("ig_id"))
            except Exception as e:
                logger.warning(f"Could not fetch additional account info: {e}")

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
                        "account_id": ig_account_id,
                        "user_id": ig_user_id,
                        "ig_id": ig_user_id,
                        "business_account_id": business_account_id,
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

                # Unsubscribe from webhook events before disconnecting
                if instagram_account.instagram_user_id and instagram_account.access_token:
                    try:
                        url = f"https://graph.instagram.com/v21.0/{instagram_account.instagram_user_id}/subscribed_apps"
                        params = {"access_token": instagram_account.access_token}
                        response = requests.delete(url, params=params, timeout=10)
                        print(f"Webhook unsubscribe on disconnect: {response.json()}")
                    except Exception as e:
                        logger.warning(f"Failed to unsubscribe webhooks on disconnect: {e}")

                instagram_account.access_token = None
                instagram_account.is_active = False
                if instagram_account.instagram_data:
                    instagram_account.instagram_data["webhook_subscribed"] = False
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

            url = f"https://graph.instagram.com/v21.0/{ig_user_id}/subscribed_apps"

            params = {
                "subscribed_fields": "comments,messages, messaging_postbacks",
                "access_token": access_token,
            }

            logger.info(f"Manual subscription to webhook events for: {ig_user_id}")

            response = requests.post(url, params=params, timeout=10)
            response_data = response.json()

            logger.info(f"Instagram subscription response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
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


class InstagramWebhookUnsubscribeView(LoginRequiredMixin, View):
    """Unsubscribe from Instagram webhook events"""

    def post(self, request):
        try:
            if not hasattr(request.user, 'instagram_account'):
                return JsonResponse({
                    'success': False,
                    'error': 'No Instagram account connected'
                }, status=400)

            instagram_account = request.user.instagram_account

            ig_user_id = instagram_account.instagram_user_id
            access_token = instagram_account.access_token

            if not ig_user_id or not access_token:
                return JsonResponse({
                    'success': False,
                    'error': 'Missing account credentials'
                }, status=400)

            # Use DELETE method to unsubscribe
            url = f"https://graph.instagram.com/v21.0/{ig_user_id}/subscribed_apps"

            params = {
                "access_token": access_token,
            }

            print(f"Unsubscribing from webhook events for: {ig_user_id}")

            response = requests.delete(url, params=params, timeout=10)
            response_data = response.json()

            print(f"Instagram unsubscribe response: {response_data}")

            if response.status_code == 200 and response_data.get("success"):
                if instagram_account.instagram_data:
                    instagram_account.instagram_data["webhook_subscribed"] = False
                else:
                    instagram_account.instagram_data = {"webhook_subscribed": False}
                instagram_account.save(update_fields=["instagram_data"])

                return JsonResponse({
                    'success': True,
                    'message': 'Successfully unsubscribed from webhook events'
                })
            else:
                error_message = response_data.get("error", {}).get("message", "Unknown error")
                logger.error(f"Failed to unsubscribe: {error_message}")
                return JsonResponse({
                    'success': False,
                    'error': error_message
                }, status=400)

        except requests.RequestException as e:
            logger.error(f"Request error during unsubscribe: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Network error: {str(e)}'
            }, status=500)
        except Exception as e:
            logger.error(f"Error unsubscribing from webhook events: {str(e)}")
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

            max_attempts = 30
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
# Landing Page
# =============================================================================

class AutomationLandingView(View):
    """Public landing page for Instagram automation feature"""
    template_name = 'instagram/automation_landing.html'

    def get(self, request):
        context = {
            'has_feature_access': False,
        }

        # Check if user has feature access
        if request.user.is_authenticated:
            can_access, _, _ = check_feature_access(request.user, 'ig_flow_builder')
            context['has_feature_access'] = can_access

        return render(request, self.template_name, context)


class FlowBuilderHelpView(LoginRequiredMixin, View):
    """Help page explaining flow builder node types"""
    template_name = 'instagram/flow_builder_help.html'

    def get(self, request):
        return render(request, self.template_name)


# =============================================================================
# Instagram Posts API
# =============================================================================

class InstagramPostsAPIView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to fetch user's Instagram posts for browsing"""

    def get(self, request):
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

        try:
            api_client = get_api_client_for_account(instagram_account)
            data = api_client.get_media(limit=50)

            posts = data.get('data', [])

            return JsonResponse({
                'success': True,
                'posts': posts,
                'count': len(posts)
            })

        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Failed to fetch Instagram posts: {str(e)}'
            })


# =============================================================================
# DM Flow Builder Views
# =============================================================================

class FlowListView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """List all DM flows for the user"""
    template_name = 'instagram/flow_list.html'

    def get(self, request):
        instagram_connected = False
        instagram_account = None
        if hasattr(request.user, 'instagram_account'):
            instagram_account = request.user.instagram_account
            instagram_connected = instagram_account.is_connected

        # Admin can see all flows, regular users see only their own
        if request.user.is_staff:
            flows = DMFlow.objects.all().select_related('user').prefetch_related('nodes')
        else:
            flows = DMFlow.objects.filter(user=request.user).prefetch_related('nodes')
        flow_count = flows.count()

        # Get flow limit from subscription
        flow_limit = None
        can_create_more = True

        if not request.user.is_staff:
            subscription = get_user_subscription(request.user)
            if subscription and subscription.plan:
                feature = subscription.plan.get_feature('ig_flow_builder')
                if feature:
                    flow_limit = feature.get('limit')
                    if flow_limit:
                        can_create_more = flow_count < flow_limit

        # Get recent sessions for activity feed
        recent_sessions = FlowSession.objects.filter(
            flow__user=request.user
        ).select_related('flow').order_by('-created_at')[:20]

        # Aggregate stats for mobile view
        from django.db.models import Sum
        stats = flows.aggregate(
            total_triggered=Sum('total_triggered'),
            total_completed=Sum('total_completed')
        )

        # Get active flow templates
        flow_templates = FlowTemplate.objects.filter(is_active=True).order_by('order', 'title')

        # Get queued flow count and API usage
        queued_count = 0
        calls_last_hour = 0
        rate_limit = QueuedFlowTrigger.get_rate_limit()
        if instagram_account:
            queued_count = QueuedFlowTrigger.objects.filter(
                account=instagram_account,
                status='pending'
            ).count()
            calls_last_hour = APICallLog.get_calls_last_hour(instagram_account)

        context = {
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
            'flows': flows,
            'flow_count': flow_count,
            'flow_limit': flow_limit,
            'can_create_more': can_create_more,
            'recent_sessions': recent_sessions,
            'total_triggered': stats['total_triggered'] or 0,
            'total_completed': stats['total_completed'] or 0,
            'flow_templates': flow_templates,
            'queued_count': queued_count,
            'calls_last_hour': calls_last_hour,
            'rate_limit': rate_limit,
        }
        return render(request, self.template_name, context)


class FlowCreateView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Create a new DM flow"""
    template_name = 'instagram/flow_form.html'

    def _check_flow_limit(self, request):
        """Check if user has reached their flow limit"""
        if request.user.is_staff:
            return False, None

        current_count = DMFlow.objects.filter(user=request.user).count()
        subscription = get_user_subscription(request.user)
        if subscription and subscription.plan:
            feature = subscription.plan.get_feature('ig_flow_builder')
            if feature:
                limit = feature.get('limit')
                if limit and current_count >= limit:
                    return True, limit
        return False, None

    def get(self, request):
        if not hasattr(request.user, 'instagram_account') or \
           not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        limit_reached, limit = self._check_flow_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} flows. Please upgrade your plan.')
            return redirect('flow_list')

        # Get available features for the user
        features = self._get_user_features(request.user)

        # Get templates for selection
        templates = FlowTemplate.objects.filter(is_active=True).order_by('order', 'title')

        # Check if a template is pre-selected via URL param
        selected_template = None
        template_id = request.GET.get('template')
        if template_id:
            try:
                selected_template = templates.get(id=template_id)
            except FlowTemplate.DoesNotExist:
                pass

        context = {
            'editing': False,
            'flow': None,
            'features': features,
            'templates': templates,
            'selected_template': selected_template,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        if not hasattr(request.user, 'instagram_account') or \
           not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        limit_reached, limit = self._check_flow_limit(request)
        if limit_reached:
            messages.error(request, f'You have reached your limit of {limit} flows.')
            return redirect('flow_list')

        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        trigger_type = request.POST.get('trigger_type', 'comment_keyword')
        instagram_post_id = request.POST.get('instagram_post_id', '').strip()
        keywords = request.POST.get('keywords', '').strip()

        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')

        # Check if post is already used by another active flow
        if instagram_post_id:
            existing_flow = DMFlow.objects.filter(
                user=request.user,
                instagram_post_id=instagram_post_id,
                is_active=True
            ).first()
            if existing_flow:
                errors.append(f'This post is already used by flow "{existing_flow.title}". Please select a different post or deactivate the existing flow.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, self.template_name, {
                'editing': False,
                'flow': {
                    'title': title,
                    'description': description,
                    'trigger_type': trigger_type,
                    'instagram_post_id': instagram_post_id,
                    'keywords': keywords,
                },
                'features': self._get_user_features(request.user),
            })

        # Check if user can have this flow active
        max_active = 1  # Default for free users

        if request.user.is_staff:
            max_active = float('inf')
        else:
            subscription = get_user_subscription(request.user)
            if subscription and subscription.plan:
                # Pro users can have unlimited active flows
                max_active = float('inf')

        active_count = DMFlow.objects.filter(user=request.user, is_active=True).count()
        is_active = active_count < max_active

        flow = DMFlow.objects.create(
            user=request.user,
            title=title,
            description=description,
            trigger_type=trigger_type,
            instagram_post_id=instagram_post_id,
            keywords=keywords,
            is_active=is_active,
        )

        # Check if a template was selected and create nodes from it
        template_id = request.POST.get('template_id')
        if template_id:
            try:
                template = FlowTemplate.objects.get(id=template_id, is_active=True)
                self._create_nodes_from_template(flow, template)
                if is_active:
                    messages.success(request, f'Flow "{title}" created from template! Review and customize your flow.')
                else:
                    messages.warning(request, f'Flow "{title}" created as inactive. You can only have {int(max_active)} active flow(s) on your plan.')
            except FlowTemplate.DoesNotExist:
                if is_active:
                    messages.success(request, f'Flow "{title}" created! Now add steps to your flow.')
                else:
                    messages.warning(request, f'Flow "{title}" created as inactive.')
        else:
            if is_active:
                messages.success(request, f'Flow "{title}" created! Now add steps to your flow.')
            else:
                messages.warning(request, f'Flow "{title}" created as inactive. You can only have {int(max_active)} active flow(s) on your plan. Deactivate another flow to activate this one.')

        return redirect('flow_edit', pk=flow.pk)

    def _get_user_features(self, user):
        """Get available flow features based on user's subscription"""
        if user.is_staff:
            return {
                'quick_replies': True,
                'follower_check': True,
                'data_collection': True,
                'advanced_branching': True,
                'ai_social_agent': True,
            }

        subscription = get_user_subscription(user)
        if not subscription:
            return {}

        return {
            'quick_replies': subscription.plan.has_feature('ig_quick_replies'),
            'follower_check': subscription.plan.has_feature('ig_follower_check'),
            'data_collection': subscription.plan.has_feature('ig_data_collection'),
            'advanced_branching': subscription.plan.has_feature('ig_advanced_branching'),
            'ai_social_agent': subscription.plan.has_feature('ai_social_agent'),
        }

    def _create_nodes_from_template(self, flow, template):
        """Create flow nodes from a template's JSON structure."""
        nodes_data = template.nodes_json or []
        id_to_node = {}  # Map template string ID -> DB node

        # First pass: create all nodes
        for idx, node_data in enumerate(nodes_data):
            # Clean config - remove connection fields (will be set in second pass)
            config = {k: v for k, v in node_data.get('config', {}).items()
                      if k not in ['true_node', 'false_node']}

            # Remove target_node from buttons (will be set in second pass)
            if 'buttons' in config:
                config['buttons'] = [
                    {k: v for k, v in btn.items() if k != 'target_node'}
                    for btn in config['buttons']
                ]

            node = FlowNode.objects.create(
                flow=flow,
                order=idx,
                node_type=node_data.get('node_type', 'message_text'),
                name=node_data.get('name', ''),
                config=config,
            )

            # Map by string ID if provided, otherwise use index
            template_id = node_data.get('id', idx)
            id_to_node[template_id] = node

            # Create quick reply options if present (without target_node for now)
            quick_replies = node_data.get('quick_replies', [])
            for qr_idx, qr_data in enumerate(quick_replies):
                QuickReplyOption.objects.create(
                    node=node,
                    title=qr_data.get('title', ''),
                    payload=qr_data.get('payload', f'qr_{qr_idx}'),
                    order=qr_idx,
                )

        # Second pass: resolve all connections using string IDs
        for idx, node_data in enumerate(nodes_data):
            template_id = node_data.get('id', idx)
            node = id_to_node[template_id]
            config = node.config or {}
            updated = False

            # Handle next_node (sequential connection)
            next_id = node_data.get('next_node')
            if next_id and next_id in id_to_node:
                node.next_node = id_to_node[next_id]
                node.save(update_fields=['next_node'])

            # Handle condition nodes (follower check, user interacted)
            if node.node_type in ['condition_follower', 'condition_user_interacted']:
                orig_config = node_data.get('config', {})
                if orig_config.get('true_node') and orig_config['true_node'] in id_to_node:
                    config['true_node_id'] = id_to_node[orig_config['true_node']].id
                    updated = True
                if orig_config.get('false_node') and orig_config['false_node'] in id_to_node:
                    config['false_node_id'] = id_to_node[orig_config['false_node']].id
                    updated = True

            # Handle button template
            if node.node_type == 'message_button_template':
                orig_buttons = node_data.get('config', {}).get('buttons', [])
                if config.get('buttons') and orig_buttons:
                    for i, orig_btn in enumerate(orig_buttons):
                        if i < len(config['buttons']) and orig_btn.get('target_node'):
                            target_id = orig_btn['target_node']
                            if target_id in id_to_node:
                                config['buttons'][i]['target_node_id'] = id_to_node[target_id].id
                                updated = True

            if updated:
                node.config = config
                node.save(update_fields=['config'])

            # Update quick reply target nodes
            quick_replies = node_data.get('quick_replies', [])
            for qr_idx, qr_data in enumerate(quick_replies):
                target_id = qr_data.get('target_node')
                if target_id and target_id in id_to_node:
                    qr_option = node.quick_reply_options.filter(order=qr_idx).first()
                    if qr_option:
                        qr_option.target_node = id_to_node[target_id]
                        qr_option.save(update_fields=['target_node'])


class FlowEditView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Edit an existing DM flow"""
    template_name = 'instagram/flow_edit.html'

    def get(self, request, pk):
        # Admin can access any flow, regular users only their own
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=pk)
        else:
            flow = get_object_or_404(DMFlow, pk=pk, user=request.user)
        nodes = flow.nodes.all().order_by('order').prefetch_related('quick_reply_options')

        features = self._get_user_features(request.user)

        # Build nodes list for JavaScript (for visual editor)
        nodes_json = []
        for node in nodes:
            # Get quick replies for this node
            quick_replies = []
            for qr in node.quick_reply_options.all().order_by('order'):
                quick_replies.append({
                    'id': qr.id,
                    'title': qr.title,
                    'payload': qr.payload,
                    'target_node_id': qr.target_node_id
                })

            node_config = node.config or {}

            # Add AI node config data if this is an AI conversation node
            if node.node_type == 'ai_conversation':
                from django.urls import reverse
                node_config['config_url'] = reverse('ai_node_config', kwargs={'node_id': node.id})
                try:
                    ai_config = node.ai_config
                    node_config['agent_name'] = ai_config.agent.name if ai_config.agent else 'No agent selected'
                    node_config['goal'] = ai_config.goal or 'No goal configured'
                except Exception:
                    node_config['agent_name'] = 'Not configured'
                    node_config['goal'] = 'Click Configure to set up'

            nodes_json.append({
                'id': node.id,
                'order': node.order,
                'node_type': node.node_type,
                'name': node.name or node.get_node_type_display(),
                'display': f"Step {node.order + 1}: {node.name or node.get_node_type_display()}",
                'config': node_config,
                'quick_replies': quick_replies,
                'next_node_id': node.next_node_id
            })

        context = {
            'flow': flow,
            'nodes': nodes,
            'nodes_json': json.dumps(nodes_json),
            'features': features,
            'node_types': FlowNode.NODE_TYPE_CHOICES,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=pk)
        else:
            flow = get_object_or_404(DMFlow, pk=pk, user=request.user)

        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        trigger_type = request.POST.get('trigger_type', 'comment_keyword')
        instagram_post_id = request.POST.get('instagram_post_id', '').strip()
        keywords = request.POST.get('keywords', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')

        # Check if post is already used by another active flow (exclude current flow)
        if instagram_post_id:
            existing_flow = DMFlow.objects.filter(
                user=request.user,
                instagram_post_id=instagram_post_id,
                is_active=True
            ).exclude(pk=pk).first()
            if existing_flow:
                errors.append(f'This post is already used by flow "{existing_flow.title}". Please select a different post or deactivate the existing flow.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('flow_edit', pk=pk)

        flow.title = title
        flow.description = description
        flow.trigger_type = trigger_type
        flow.instagram_post_id = instagram_post_id
        flow.keywords = keywords
        flow.is_active = is_active
        flow.save()

        messages.success(request, f'Flow "{title}" updated!')
        return redirect('flow_edit', pk=pk)

    def _get_user_features(self, user):
        """Get available flow features based on user's subscription"""
        if user.is_staff:
            return {
                'quick_replies': True,
                'follower_check': True,
                'data_collection': True,
                'advanced_branching': True,
                'ai_social_agent': True,
            }

        subscription = get_user_subscription(user)
        if not subscription:
            return {}

        return {
            'quick_replies': subscription.plan.has_feature('ig_quick_replies'),
            'follower_check': subscription.plan.has_feature('ig_follower_check'),
            'data_collection': subscription.plan.has_feature('ig_data_collection'),
            'advanced_branching': subscription.plan.has_feature('ig_advanced_branching'),
            'ai_social_agent': subscription.plan.has_feature('ai_social_agent'),
        }


class FlowSaveVisualView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to save flow from visual editor"""

    def post(self, request, pk):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=pk)
        else:
            flow = get_object_or_404(DMFlow, pk=pk, user=request.user)

        try:
            data = json.loads(request.body)
            nodes_data = data.get('nodes', [])
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        # Track all node IDs we want to keep
        keep_node_ids = set()
        new_node_map = {}  # Maps drawflow temp id (string) to new db id
        node_objects = {}  # Maps original id to node object for second pass

        try:
            with transaction.atomic():
                # Step 1: Identify which existing nodes to keep (those being updated)
                existing_node_ids_to_keep = set()
                for node_data in nodes_data:
                    node_id = node_data.get('id')
                    if node_id and isinstance(node_id, int):
                        existing_node_ids_to_keep.add(node_id)

                # Step 2: Delete nodes that are NOT being kept BEFORE creating new ones
                # This prevents unique constraint violations on (flow_id, order)
                deleted_count = flow.nodes.exclude(id__in=existing_node_ids_to_keep).delete()[0]

                # Step 3: Temporarily shift all existing node orders to avoid unique constraint conflicts
                # This handles cases where nodes are being reordered (e.g., node A order 0->1, node B order 1->0)
                for idx, node_id in enumerate(existing_node_ids_to_keep):
                    FlowNode.objects.filter(id=node_id).update(order=10000 + idx)

                # Step 4: Create/update all nodes (without resolving target_node_ids)
                for node_data in nodes_data:
                    node_id = node_data.get('id')  # Database ID (null for new nodes)
                    drawflow_id = node_data.get('drawflow_id')  # Drawflow ID for mapping (visual editor)
                    temp_id = node_data.get('temp_id')  # Temp ID for mapping (form editor)
                    node_type = node_data.get('node_type')
                    order = node_data.get('order', 0)
                    # Deep copy config to prevent any shared reference issues
                    config = copy.deepcopy(node_data.get('config', {}))

                    # Filter out empty variations
                    if 'variations' in config:
                        config['variations'] = [v for v in config['variations'] if v and v.strip()]
                        if not config['variations']:
                            del config['variations']

                    # Save visual editor positions in config
                    pos_x = node_data.get('pos_x')
                    pos_y = node_data.get('pos_y')
                    if pos_x is not None:
                        config['_pos_x'] = pos_x
                    if pos_y is not None:
                        config['_pos_y'] = pos_y

                    if node_id and isinstance(node_id, int):
                        # Update existing node
                        try:
                            node = FlowNode.objects.get(id=node_id, flow=flow)
                            node.order = order
                            node.node_type = node_type
                            node.config = config
                            node.save()
                            keep_node_ids.add(node.id)
                            node_objects[node_id] = (node, node_data)
                            # Map all IDs to db_id for existing nodes
                            if drawflow_id:
                                new_node_map[str(drawflow_id)] = node.id
                            if temp_id:
                                new_node_map[str(temp_id)] = node.id
                            new_node_map[str(node.id)] = node.id  # Also map DB ID to itself
                        except FlowNode.DoesNotExist:
                            # Node was deleted from DB, create new one
                            node = FlowNode.objects.create(
                                flow=flow,
                                order=order,
                                node_type=node_type,
                                config=config
                            )
                            keep_node_ids.add(node.id)
                            if drawflow_id:
                                new_node_map[str(drawflow_id)] = node.id
                            if temp_id:
                                new_node_map[str(temp_id)] = node.id
                            node_objects[node_id] = (node, node_data)
                    else:
                        # Create new node
                        node = FlowNode.objects.create(
                            flow=flow,
                            order=order,
                            node_type=node_type,
                            config=config
                        )
                        keep_node_ids.add(node.id)
                        # Map both drawflow_id and temp_id for new nodes
                        if drawflow_id:
                            new_node_map[str(drawflow_id)] = node.id
                        if temp_id:
                            new_node_map[str(temp_id)] = node.id
                        # Always add to node_objects for second pass processing
                        obj_key = temp_id or drawflow_id or f"new_db_{node.id}"
                        node_objects[obj_key] = (node, node_data)

                # Helper to resolve target_node_id (handles int, "new_X", "node_X", etc.)
                def resolve_target_id(target_id):
                    if target_id is None or target_id == '':
                        return None
                    if isinstance(target_id, int):
                        # If it's already a DB ID, return it (if still valid)
                        return target_id if target_id in [n.id for n, _ in node_objects.values()] else None
                    if isinstance(target_id, str):
                        # Try direct lookup first (handles node_X, new_X, and string DB IDs)
                        if target_id in new_node_map:
                            return new_node_map[target_id]
                        # Try stripping prefixes
                        if target_id.startswith('new_'):
                            stripped = target_id[4:]
                            if stripped in new_node_map:
                                return new_node_map[stripped]
                        if target_id.startswith('node_'):
                            stripped = target_id[5:]
                            if stripped in new_node_map:
                                return new_node_map[stripped]
                        # Try parsing as int (DB ID)
                        try:
                            db_id = int(target_id)
                            return db_id if str(db_id) in new_node_map else None
                        except ValueError:
                            pass
                    return None

                # Second pass: Update target_node_ids now that all nodes exist
                for node, node_data in node_objects.values():
                    # Deep copy config to prevent shared reference issues when modifying
                    config = copy.deepcopy(node.config) if node.config else {}
                    config_updated = False

                    # Handle next_node_id for regular sequential connections
                    # Check if 'next_node_id' key exists in data (could be null to clear)
                    if 'next_node_id' in node_data:
                        next_node_id = node_data.get('next_node_id')
                        resolved_next = resolve_target_id(next_node_id) if next_node_id else None
                        if resolved_next != node.next_node_id:
                            node.next_node_id = resolved_next
                            node.save(update_fields=['next_node_id'])

                    # Handle button template target_node_ids
                    if node.node_type == 'message_button_template' and config.get('buttons'):
                        for btn in config['buttons']:
                            if 'target_node_id' in btn:
                                resolved_id = resolve_target_id(btn['target_node_id'])
                                btn['target_node_id'] = resolved_id
                                config_updated = True

                    # Handle condition_follower target_node_ids
                    if node.node_type == 'condition_follower':
                        if 'true_node_id' in config:
                            config['true_node_id'] = resolve_target_id(config['true_node_id'])
                            config_updated = True
                        if 'false_node_id' in config:
                            config['false_node_id'] = resolve_target_id(config['false_node_id'])
                            config_updated = True

                    # Handle condition_user_interacted target_node_ids
                    if node.node_type == 'condition_user_interacted':
                        if 'true_node_id' in config:
                            config['true_node_id'] = resolve_target_id(config['true_node_id'])
                            config_updated = True
                        if 'false_node_id' in config:
                            config['false_node_id'] = resolve_target_id(config['false_node_id'])
                            config_updated = True

                    if config_updated:
                        node.config = config
                        node.save()

                    # Handle quick replies
                    quick_replies_data = node_data.get('quick_replies', [])

                    if node.node_type == 'message_quick_reply':
                        # Delete existing quick replies for this node
                        node.quick_reply_options.all().delete()

                        # Create new quick replies with resolved target_node_ids
                        for idx, qr_data in enumerate(quick_replies_data):
                            raw_target = qr_data.get('target_node_id')
                            resolved_target = resolve_target_id(raw_target)
                            QuickReplyOption.objects.create(
                                node=node,
                                title=qr_data.get('title', ''),
                                payload=qr_data.get('payload', f'qr_{idx}'),
                                order=idx,
                                target_node_id=resolved_target
                            )

                # Note: Deletion already happened at the beginning of the transaction

        except Exception as e:
            logger.exception(f"Error saving flow {pk}: {str(e)}")
            return JsonResponse({'error': f'Failed to save flow: {str(e)}'}, status=500)

        # Collect AI node config URLs for NEWLY CREATED AI conversation nodes only
        ai_config_urls = {}
        from django.urls import reverse
        for node, node_data in node_objects.values():
            if node.node_type == 'ai_conversation':
                # Only include if this is a new node (original id was not an integer db id)
                original_id = node_data.get('id')
                if not original_id or not isinstance(original_id, int):
                    ai_config_urls[node.id] = reverse('ai_node_config', kwargs={'node_id': node.id})

        return JsonResponse({
            'success': True,
            'message': f'Flow saved successfully. {len(keep_node_ids)} nodes saved.',
            'node_ids': new_node_map,
            'deleted': deleted_count,
            'ai_config_urls': ai_config_urls
        })


class FlowDeleteView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Delete a DM flow - only owner can delete"""

    def post(self, request, pk):
        # Only the owner can delete, not staff
        flow = get_object_or_404(DMFlow, pk=pk, user=request.user)
        title = flow.title
        flow.delete()
        messages.success(request, f'Flow "{title}" deleted.')
        return redirect('flow_list')


class FlowToggleActiveView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Toggle flow active status - only owner can toggle"""

    def post(self, request, pk):
        # Only the owner can toggle active status, not staff
        flow = get_object_or_404(DMFlow, pk=pk, user=request.user)

        try:
            data = json.loads(request.body)
            is_active = data.get('is_active', False)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        # If trying to activate, check if user can have more active flows
        if is_active and not flow.is_active:
            # Check active flow limit based on subscription
            max_active = 1  # Default for free users

            if request.user.is_staff:
                max_active = float('inf')
            else:
                subscription = get_user_subscription(request.user)
                if subscription and subscription.plan:
                    # Pro users can have unlimited active flows
                    max_active = float('inf')

            active_count = DMFlow.objects.filter(user=request.user, is_active=True).count()
            if active_count >= max_active:
                return JsonResponse({
                    'success': False,
                    'error': f'You can only have {int(max_active)} active flow(s) on your current plan. Please upgrade or deactivate another flow first.'
                }, status=400)

        flow.is_active = is_active
        flow.save(update_fields=['is_active'])

        return JsonResponse({
            'success': True,
            'is_active': flow.is_active
        })


class FlowSessionsView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """View sessions/logs for a flow"""
    template_name = 'instagram/flow_sessions.html'
    paginate_by = 20

    def get(self, request, pk):
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=pk)
        else:
            flow = get_object_or_404(DMFlow, pk=pk, user=request.user)

        sessions = flow.sessions.all().order_by('-created_at')

        # Filter by status
        status_filter = request.GET.get('status', '')
        if status_filter:
            sessions = sessions.filter(status=status_filter)

        # Filter by username
        username_filter = request.GET.get('username', '').strip()
        if username_filter:
            sessions = sessions.filter(instagram_username__icontains=username_filter)

        # Pagination
        paginator = Paginator(sessions, self.paginate_by)
        page = request.GET.get('page', 1)

        try:
            sessions_page = paginator.page(page)
        except PageNotAnInteger:
            sessions_page = paginator.page(1)
        except EmptyPage:
            sessions_page = paginator.page(paginator.num_pages)

        # Get status choices for filter dropdown
        status_choices = FlowSession.STATUS_CHOICES

        context = {
            'flow': flow,
            'sessions': sessions_page,
            'status_filter': status_filter,
            'username_filter': username_filter,
            'status_choices': status_choices,
            'total_count': paginator.count,
        }
        return render(request, self.template_name, context)


class FlowSessionDetailView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """View detailed execution logs for a session"""
    template_name = 'instagram/flow_session_detail.html'

    def get(self, request, pk, session_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=pk)
        else:
            flow = get_object_or_404(DMFlow, pk=pk, user=request.user)
        session = get_object_or_404(FlowSession, pk=session_id, flow=flow)

        # Get all execution logs for this session
        logs = session.execution_logs.all().order_by('created_at').select_related('node')

        context = {
            'flow': flow,
            'session': session,
            'logs': logs,
        }
        return render(request, self.template_name, context)


# =============================================================================
# Flow Node API Views
# =============================================================================

class FlowNodeCreateView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to create a new node"""

    def post(self, request, flow_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=flow_id)
        else:
            flow = get_object_or_404(DMFlow, pk=flow_id, user=request.user)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        node_type = data.get('node_type')
        name = data.get('name', '')
        config = data.get('config', {})

        if not node_type:
            return JsonResponse({'error': 'node_type is required'}, status=400)

        # Validate follower check node requires interaction nodes
        if node_type == 'condition_follower':
            has_interaction_node = flow.nodes.filter(
                node_type__in=['message_quick_reply', 'message_button_template']
            ).exists()
            if not has_interaction_node:
                return JsonResponse({
                    'error': 'Follower Check requires a Quick Reply or Button Template step first. '
                             'The user must interact (click a button) before we can check their follower status.'
                }, status=400)

        # Calculate next order with proper locking to avoid race conditions
        from django.db import transaction
        with transaction.atomic():
            # Lock the flow's nodes to prevent concurrent modifications
            existing_orders = list(flow.nodes.select_for_update().values_list('order', flat=True))
            if existing_orders:
                next_order = max(existing_orders) + 1
            else:
                next_order = 0

            node = FlowNode.objects.create(
                flow=flow,
                order=next_order,
                node_type=node_type,
                name=name,
                config=config,
            )

        # Handle quick reply options if provided
        quick_replies = data.get('quick_replies', [])
        for i, qr in enumerate(quick_replies):
            target_node = None
            target_node_id = qr.get('target_node_id')
            if target_node_id:
                try:
                    target_node = FlowNode.objects.get(id=target_node_id, flow=flow)
                except FlowNode.DoesNotExist:
                    pass

            QuickReplyOption.objects.create(
                node=node,
                title=qr.get('title', '')[:20],
                payload=qr.get('payload', f'opt_{i}'),
                order=i,
                target_node=target_node,
            )

        return JsonResponse({
            'success': True,
            'node_id': node.id,
            'order': node.order,
        })


class FlowNodeUpdateView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to update a node"""

    def post(self, request, flow_id, node_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=flow_id)
        else:
            flow = get_object_or_404(DMFlow, pk=flow_id, user=request.user)
        node = get_object_or_404(FlowNode, pk=node_id, flow=flow)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if 'name' in data:
            node.name = data['name']
        if 'config' in data:
            node.config = data['config']
        if 'next_node_id' in data:
            if data['next_node_id']:
                try:
                    next_node = FlowNode.objects.get(pk=data['next_node_id'], flow=flow)
                    node.next_node = next_node
                except FlowNode.DoesNotExist:
                    pass
            else:
                node.next_node = None

        node.save()

        # Handle quick reply options if provided
        if 'quick_replies' in data:
            # Delete existing and recreate
            node.quick_reply_options.all().delete()
            for i, qr in enumerate(data['quick_replies']):
                target_node_id = qr.get('target_node_id')
                target_node = None
                if target_node_id:
                    try:
                        target_node = FlowNode.objects.get(pk=target_node_id, flow=flow)
                    except FlowNode.DoesNotExist:
                        pass

                QuickReplyOption.objects.create(
                    node=node,
                    title=qr.get('title', '')[:20],
                    payload=qr.get('payload', f'opt_{i}'),
                    order=i,
                    target_node=target_node,
                )

        return JsonResponse({'success': True})


class FlowNodeDeleteView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to delete a node"""

    def post(self, request, flow_id, node_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=flow_id)
        else:
            flow = get_object_or_404(DMFlow, pk=flow_id, user=request.user)
        node = get_object_or_404(FlowNode, pk=node_id, flow=flow)

        # Prevent deleting interaction nodes if follower check depends on them
        if node.node_type in ['message_quick_reply', 'message_button_template']:
            has_follower_check = flow.nodes.filter(node_type='condition_follower').exists()
            if has_follower_check:
                interaction_count = flow.nodes.filter(
                    node_type__in=['message_quick_reply', 'message_button_template']
                ).count()
                if interaction_count <= 1:
                    return JsonResponse({
                        'error': 'Cannot delete this step because a Follower Check step depends on it. '
                                 'Remove the Follower Check step first, or add another Quick Reply/Button Template step.'
                    }, status=400)

        node.delete()

        # Reorder remaining nodes
        for i, n in enumerate(flow.nodes.all().order_by('order')):
            if n.order != i:
                n.order = i
                n.save(update_fields=['order'])

        return JsonResponse({'success': True})


class FlowNodeReorderView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to reorder nodes"""

    def post(self, request, flow_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=flow_id)
        else:
            flow = get_object_or_404(DMFlow, pk=flow_id, user=request.user)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        node_order = data.get('node_order', [])  # List of node IDs in new order

        for i, node_id in enumerate(node_order):
            try:
                node = FlowNode.objects.get(pk=node_id, flow=flow)
                node.order = i
                node.save(update_fields=['order'])
            except FlowNode.DoesNotExist:
                pass

        return JsonResponse({'success': True})


class FlowNodeDetailView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """API endpoint to get node details"""

    def get(self, request, flow_id, node_id):
        if request.user.is_staff:
            flow = get_object_or_404(DMFlow, pk=flow_id)
        else:
            flow = get_object_or_404(DMFlow, pk=flow_id, user=request.user)
        node = get_object_or_404(FlowNode, pk=node_id, flow=flow)

        quick_replies = [
            {
                'id': qr.id,
                'title': qr.title,
                'payload': qr.payload,
                'target_node_id': qr.target_node_id,
                'order': qr.order,
            }
            for qr in node.quick_reply_options.all().order_by('order')
        ]

        return JsonResponse({
            'id': node.id,
            'order': node.order,
            'node_type': node.node_type,
            'name': node.name,
            'config': node.config,
            'next_node_id': node.next_node_id,
            'quick_replies': quick_replies,
        })


# =============================================================================
# Leads Views
# =============================================================================

class LeadsListView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """View all collected leads"""
    template_name = 'instagram/leads_list.html'

    def get(self, request):
        leads = CollectedLead.objects.filter(
            user=request.user
        ).select_related('flow').order_by('-created_at')

        context = {
            'leads': leads,
            'total_leads': leads.count(),
        }
        return render(request, self.template_name, context)


class LeadsExportView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Export leads as CSV"""

    def get(self, request):
        leads = CollectedLead.objects.filter(user=request.user).order_by('-created_at')

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="leads.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Instagram Username', 'Name', 'Email', 'Phone',
            'Is Follower', 'Flow', 'Created At'
        ])

        for lead in leads:
            writer.writerow([
                lead.instagram_username,
                lead.name,
                lead.email,
                lead.phone,
                'Yes' if lead.is_follower else 'No',
                lead.flow.title if lead.flow else '',
                lead.created_at.strftime('%Y-%m-%d %H:%M'),
            ])

        return response


class LeadDetailView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """View a single lead's details"""
    template_name = 'instagram/lead_detail.html'

    def get(self, request, pk):
        lead = get_object_or_404(CollectedLead, pk=pk, user=request.user)

        context = {
            'lead': lead,
        }
        return render(request, self.template_name, context)


# =============================================================================
# Queued Flow Triggers Views
# =============================================================================

class QueuedFlowListView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """View all queued flow triggers for the user's account"""
    template_name = 'instagram/queued_flows.html'

    def get(self, request):
        # Get user's Instagram account
        instagram_account = getattr(request.user, 'instagram_account', None)
        if not instagram_account:
            messages.warning(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        # Get rate limit info
        calls_last_hour = APICallLog.get_calls_last_hour(instagram_account)
        rate_limit = QueuedFlowTrigger.get_rate_limit()
        available_slots = max(0, rate_limit - calls_last_hour)

        # Calculate how many flows can be triggered (assume ~10 API calls per flow)
        CALLS_PER_FLOW = 10
        max_triggerable = available_slots // CALLS_PER_FLOW

        # Get pending queued triggers
        queued_flows = QueuedFlowTrigger.objects.filter(
            account=instagram_account,
            status='pending'
        ).select_related('flow').order_by('created_at')

        # Get recently processed (last 24 hours)
        recent_processed = QueuedFlowTrigger.objects.filter(
            account=instagram_account,
            status__in=['completed', 'failed'],
            processed_at__gte=timezone.now() - timedelta(hours=24)
        ).select_related('flow').order_by('-processed_at')[:10]

        context = {
            'queued_flows': queued_flows,
            'recent_processed': recent_processed,
            'calls_last_hour': calls_last_hour,
            'rate_limit': rate_limit,
            'available_slots': available_slots,
            'max_triggerable': max_triggerable,
            'pending_count': queued_flows.count(),
        }
        return render(request, self.template_name, context)


class QueuedFlowTriggerView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Manually trigger a queued flow"""

    def post(self, request, pk):
        # Get the queued trigger
        instagram_account = getattr(request.user, 'instagram_account', None)
        if not instagram_account:
            messages.error(request, 'Instagram account not connected.')
            return redirect('queued_flows')

        queued = get_object_or_404(
            QueuedFlowTrigger,
            pk=pk,
            account=instagram_account,
            status='pending'
        )

        # Check rate limit - need at least 20 slots free (buffer for flow to complete)
        calls_last_hour = APICallLog.get_calls_last_hour(instagram_account)
        rate_limit = QueuedFlowTrigger.get_rate_limit()
        TRIGGER_THRESHOLD = rate_limit - 20  # Need 20 slots buffer

        if calls_last_hour > TRIGGER_THRESHOLD:
            available = rate_limit - calls_last_hour
            messages.error(
                request,
                f'Only {available} API calls available. Need at least 20 free slots to safely trigger a flow. Try later.'
            )
            return redirect('queued_flows')

        # Check if already processed (dedup)
        ctx = queued.trigger_context
        if FlowSession.objects.filter(trigger_comment_id=ctx.get('comment_id', '')).exists():
            queued.status = 'completed'
            queued.processed_at = timezone.now()
            queued.save()
            messages.info(request, 'This comment was already processed.')
            return redirect('queued_flows')

        # Trigger the flow
        try:
            queued.status = 'processing'
            queued.save()

            engine = FlowEngine(instagram_account)

            if queued.trigger_type == 'comment':
                logger.info(f"Triggering queued flow with context: comment_id={ctx['comment_id']}, commenter_id={ctx['commenter_id']}, commenter_username={ctx['commenter_username']}")
                engine.trigger_flow_from_comment(
                    flow=queued.flow,
                    comment_id=ctx['comment_id'],
                    post_id=ctx['post_id'],
                    commenter_id=ctx['commenter_id'],
                    commenter_username=ctx['commenter_username'],
                    comment_text=ctx['comment_text'],
                )

            queued.status = 'completed'
            queued.processed_at = timezone.now()
            queued.save()

            messages.success(request, f'Flow "{queued.flow.title}" triggered successfully!')

        except Exception as e:
            logger.error(f"Error triggering queued flow {pk}: {str(e)}")
            queued.status = 'failed'
            queued.error_message = str(e)
            queued.processed_at = timezone.now()
            queued.save()
            messages.error(request, f'Failed to trigger flow: {str(e)}')

        return redirect('queued_flows')


class QueuedFlowDeleteView(IGFlowBuilderFeatureMixin, LoginRequiredMixin, View):
    """Delete a queued flow trigger"""

    def post(self, request, pk):
        instagram_account = getattr(request.user, 'instagram_account', None)
        if not instagram_account:
            messages.error(request, 'Instagram account not connected.')
            return redirect('queued_flows')

        queued = get_object_or_404(
            QueuedFlowTrigger,
            pk=pk,
            account=instagram_account,
            status='pending'
        )

        flow_title = queued.flow.title
        queued.delete()
        messages.success(request, f'Removed queued trigger for "{flow_title}".')

        return redirect('queued_flows')


# =============================================================================
# Instagram Webhook Handler
# =============================================================================

@method_decorator(csrf_exempt, name='dispatch')
class InstagramWebhookView(View):
    """Handle Instagram webhook events for DM flow automation"""

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
            print(payload)
            logger.info(f"Instagram webhook received: {json.dumps(payload)[:1000]}")

            for entry in payload.get('entry', []):
                ig_business_account_id = str(entry.get('id', ''))
                logger.info(f"Processing webhook entry: id={ig_business_account_id}")

                # Handle comment changes
                for change in entry.get('changes', []):
                    if change.get('field') == 'comments':
                        self.handle_comment(change.get('value', {}), ig_business_account_id)

                # Handle message events (quick replies, text replies)
                for messaging in entry.get('messaging', []):
                    self.handle_message(messaging, ig_business_account_id)

            return JsonResponse({'status': 'ok'})

        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            return JsonResponse({'status': 'error'}, status=500)

    def handle_comment(self, comment_data, ig_business_account_id):
        """Process a new comment and trigger matching flow"""
        comment_id = comment_data.get('id')
        post_id = comment_data.get('media', {}).get('id', '')
        comment_text = comment_data.get('text', '')
        commenter_id = comment_data.get('from', {}).get('id', '')
        commenter_username = comment_data.get('from', {}).get('username', '')
        parent_id = comment_data.get('parent_id', '')

        # Skip replies to comments
        if parent_id:
            logger.info(f"Skipping comment {comment_id} - it's a reply")
            return

        if not comment_id:
            logger.warning("Comment event missing comment_id")
            return

        # Check for duplicate
        if FlowSession.objects.filter(trigger_comment_id=comment_id).exists():
            logger.info(f"Comment {comment_id} already processed")
            return

        # Find Instagram account
        instagram_account = self._find_instagram_account(ig_business_account_id)
        if not instagram_account:
            logger.warning(f"No Instagram account found for {ig_business_account_id}")
            return

        user = instagram_account.user

        # Skip own comments
        if commenter_id == ig_business_account_id or commenter_id == instagram_account.instagram_user_id:
            logger.info(f"Skipping comment {comment_id} - from account owner")
            return

        # Find matching flow
        flow = find_matching_flow(user, post_id, comment_text)
        if not flow:
            logger.info(f"No matching flow for comment {comment_id}")
            return

        # Check rate limit before triggering
        calls_last_hour = APICallLog.get_calls_last_hour(instagram_account)
        rate_limit = QueuedFlowTrigger.get_rate_limit()

        if calls_last_hour >= rate_limit:
            # Queue the flow trigger for later
            QueuedFlowTrigger.objects.get_or_create(
                account=instagram_account,
                instagram_event_id=comment_id,
                defaults={
                    'flow': flow,
                    'trigger_type': 'comment',
                    'trigger_context': {
                        'comment_id': comment_id,
                        'post_id': post_id,
                        'commenter_id': commenter_id,
                        'commenter_username': commenter_username,
                        'comment_text': comment_text,
                    }
                }
            )
            logger.info(f"Rate limited ({calls_last_hour}/{rate_limit}) - queued flow trigger for comment {comment_id}")
            return

        # Trigger the flow
        try:
            engine = FlowEngine(instagram_account)
            engine.trigger_flow_from_comment(
                flow=flow,
                comment_id=comment_id,
                post_id=post_id,
                commenter_id=commenter_id,
                commenter_username=commenter_username,
                comment_text=comment_text
            )
            logger.info(f"Triggered flow '{flow.title}' for comment {comment_id}")
        except Exception as e:
            logger.error(f"Error triggering flow: {str(e)}")

    def handle_message(self, messaging_data, ig_business_account_id):
        """Process incoming messages (quick reply clicks, text replies)"""
        sender = messaging_data.get('sender', {})
        sender_id = sender.get('id', '')
        recipient = messaging_data.get('recipient', {})
        recipient_id = recipient.get('id', '')
        message = messaging_data.get('message', {})
        timestamp = messaging_data.get('timestamp', '')

        # Skip echo messages (messages sent BY us, not TO us)
        if message.get('is_echo'):
            logger.debug(f"Skipping echo message from {sender_id}")
            return

        # Get message ID for deduplication
        message_id = message.get('mid', '') if message else ''
        postback = messaging_data.get('postback', {})
        postback_mid = postback.get('mid', '') if postback else ''

        logger.info(f"Message event - sender: {sender_id}, recipient: {recipient_id}, mid: {message_id or postback_mid}")

        # Skip if sender is our own account (another way echoes might come through)
        if sender_id == ig_business_account_id or sender_id == recipient_id:
            logger.debug(f"Skipping message from our own account: {sender_id}")
            return

        if not sender_id or (not message and not postback):
            return

        # Find Instagram account - try entry.id first, then recipient.id
        instagram_account = self._find_instagram_account(ig_business_account_id)
        if not instagram_account and recipient_id:
            instagram_account = self._find_instagram_account(recipient_id)
        if not instagram_account:
            logger.warning(f"No Instagram account found for entry_id={ig_business_account_id} or recipient_id={recipient_id}")
            return

        # Check for postback (from button template) - handle first since we already extracted it
        if postback:
            payload = postback.get('payload', '')
            logger.info(f"Button template postback received: {payload}")
            self._handle_quick_reply_or_postback(sender_id, payload, instagram_account, postback_mid)
            return

        # Check for quick reply (inside message object)
        quick_reply = message.get('quick_reply', {})
        if quick_reply:
            payload = quick_reply.get('payload', '')
            self._handle_quick_reply_or_postback(sender_id, payload, instagram_account, message_id)
            return

        # Check for text message (for data collection)
        text = message.get('text', '')
        if text:
            self._handle_text_message(sender_id, text, instagram_account, message_id)

    def _handle_quick_reply_or_postback(self, sender_id, payload, instagram_account, message_id=None):
        """Handle quick reply button click or button template postback"""
        logger.info(f"Quick reply/postback from {sender_id}: {payload}")

        # Parse payload to get session info
        parsed = parse_quick_reply_payload(payload)
        if not parsed:
            logger.error(f"Could not parse payload: {payload}")
            return

        session_id = parsed['session_id']

        try:
            session = FlowSession.objects.get(
                id=session_id,
                flow__user=instagram_account.user
            )
        except FlowSession.DoesNotExist:
            logger.error(f"Session {session_id} not found")
            return

        # Deduplication: Check if this exact message was already processed (same webhook sent twice)
        if message_id:
            already_processed = FlowExecutionLog.objects.filter(
                session=session,
                action='quick_reply_received',
                details__message_id=message_id
            ).exists()
            if already_processed:
                logger.info(f"Duplicate webhook ignored - message_id {message_id} already processed")
                return

        # Allow clicks even on completed sessions - user can explore all buttons anytime
        # Just reactivate the session
        if session.status == 'completed':
            logger.info(f"Reactivating completed session {session_id} for new button click")
            session.status = 'active'
            session.save(update_fields=['status', 'updated_at'])

        try:
            engine = FlowEngine(instagram_account)
            # Determine if this is a quick reply (_opt_) or button postback (_btn_)
            if '_btn_' in payload:
                engine.handle_button_postback(session, payload, message_id)
            else:
                engine.handle_quick_reply_click(session, payload, message_id)
        except Exception as e:
            logger.error(f"Error handling quick reply/postback: {str(e)}")

    def _handle_text_message(self, sender_id, text, instagram_account, message_id=None):
        """Handle text message (for data collection)"""
        logger.info(f"Text message from {sender_id}: {text[:50]}...")

        # Find active session waiting for reply
        session = find_session_for_message(sender_id, instagram_account.user)
        if not session:
            logger.info(f"No active session for {sender_id}")
            return

        if session.status != 'waiting_reply':
            logger.info(f"Session {session.id} not waiting for reply")
            return

        # Deduplication: Check if this message was already processed
        if message_id:
            already_processed = FlowExecutionLog.objects.filter(
                session=session,
                action='text_reply_received',
                details__message_id=message_id
            ).exists()
            if already_processed:
                logger.info(f"Duplicate webhook ignored - message_id {message_id} already processed")
                return

        try:
            engine = FlowEngine(instagram_account)
            engine.handle_text_reply(session, text, message_id)
        except Exception as e:
            logger.error(f"Error handling text reply: {str(e)}")

    def _find_instagram_account(self, ig_business_account_id):
        """Find Instagram account by various ID fields"""
        if not ig_business_account_id:
            return None

        # Try multiple methods to find the account
        lookup_fields = [
            {'instagram_user_id': ig_business_account_id},
            {'instagram_data__account_id': ig_business_account_id},
            {'instagram_data__business_account_id': ig_business_account_id},
            {'instagram_data__user_id': ig_business_account_id},
            {'instagram_data__ig_id': ig_business_account_id},
        ]

        for lookup in lookup_fields:
            try:
                return InstagramAccount.objects.get(
                    **lookup,
                    is_active=True
                )
            except InstagramAccount.DoesNotExist:
                continue

        # Fallback: If only one active account with webhook subscribed, use it
        # This handles cases where the webhook ID format changed
        active_accounts = InstagramAccount.objects.filter(
            is_active=True,
            instagram_data__webhook_subscribed=True
        )
        if active_accounts.count() == 1:
            logger.info(f"Using fallback: only one active webhook account found")
            return active_accounts.first()

        logger.warning(f"Account lookup failed for ID: {ig_business_account_id}")
        return None


# =============================================================================
# Facebook/Instagram App Callback Endpoints
# =============================================================================

def parse_signed_request(signed_request, app_secret):
    """Parse and verify a signed_request from Facebook."""
    try:
        encoded_sig, payload = signed_request.split('.', 1)
        sig = base64.urlsafe_b64decode(encoded_sig + '==')
        data = json.loads(base64.urlsafe_b64decode(payload + '=='))
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
    """Handle Facebook/Instagram Data Deletion Requests"""

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

            if user_id:
                try:
                    instagram_account = InstagramAccount.objects.filter(
                        instagram_user_id=user_id
                    ).first()

                    if instagram_account:
                        # Delete all related data
                        DMFlow.objects.filter(user=instagram_account.user).delete()
                        CollectedLead.objects.filter(user=instagram_account.user).delete()
                        instagram_account.delete()
                        logger.info(f"Deleted Instagram data for user_id: {user_id}")
                except Exception as e:
                    logger.error(f"Error deleting data for user_id {user_id}: {e}")

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
    """Handle Facebook/Instagram Deauthorization Callbacks"""

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
