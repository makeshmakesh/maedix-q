import json
import logging
import requests
import urllib.parse
from datetime import datetime, timedelta
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
from core.subscription_utils import check_feature_access

logger = logging.getLogger(__name__)


class IGAutomationFeatureRequiredMixin:
    """Mixin to check if user has ig_automation feature access"""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        can_access, message, _ = check_feature_access(request.user, 'ig_automation')
        if not can_access:
            messages.error(request, 'You need to upgrade your plan to access Instagram Automation.')
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

            # Step 3: Fetch user details
            user_info_response = requests.get(
                "https://graph.instagram.com/v21.0/me",
                params={
                    "fields": "id,username",
                    "access_token": access_token,
                },
                timeout=10,
            )

            if not user_info_response.ok:
                raise ValueError(
                    f"Failed to fetch Instagram user info: {user_info_response.text}"
                )

            user_info = user_info_response.json()

            # Step 4: Save or update InstagramAccount
            # The ID from /me endpoint IS the Instagram Business Account ID
            # when using instagram_business_* scopes
            business_account_id = str(user_info.get("id", ""))

            instagram_account, created = InstagramAccount.objects.update_or_create(
                user=request.user,
                defaults={
                    "instagram_user_id": business_account_id,
                    "username": user_info.get("username", ""),
                    "access_token": access_token,
                    "token_expires_at": token_expires_at,
                    "is_active": True,
                    "instagram_data": {
                        "user_info": user_info,
                        "business_account_id": business_account_id,  # Store explicitly
                        "connected_at": str(timezone.now()),
                    },
                },
            )

            logger.info(f"Instagram connected for user {request.user.id}: business_account_id={business_account_id}")

            action = "connected" if created else "reconnected"
            messages.success(request, f"Instagram account @{user_info.get('username')} {action}!")

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

        # Get recent comment events
        recent_events = InstagramCommentEvent.objects.filter(
            user=request.user
        ).select_related('automation')[:20]

        context = {
            'instagram_connected': instagram_connected,
            'instagram_account': instagram_account,
            'automations': automations,
            'recent_events': recent_events,
        }
        return render(request, self.template_name, context)


class AutomationCreateView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Create a new Instagram automation"""
    template_name = 'instagram/automation_form.html'

    def get(self, request):
        # Check if Instagram is connected
        if not hasattr(request.user, 'instagram_account') or \
           not request.user.instagram_account.is_connected:
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

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

        title = request.POST.get('title', '').strip()
        instagram_post_id = request.POST.get('instagram_post_id', '').strip()
        keywords = request.POST.get('keywords', '').strip()
        comment_reply = request.POST.get('comment_reply', '').strip()
        followup_dm = request.POST.get('followup_dm', '').strip()
        require_follow = request.POST.get('require_follow') == 'on'
        follow_request_message = request.POST.get('follow_request_message', '').strip()

        # Validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')
        if not instagram_post_id:
            errors.append('Please select an Instagram post.')
        if not comment_reply:
            errors.append('Comment reply text is required.')
        if not followup_dm:
            errors.append('Follow-up DM text is required.')
        if require_follow and not follow_request_message:
            errors.append('Follow request message is required when "Require Follow" is enabled.')

        if errors:
            for error in errors:
                messages.error(request, error)
            context = {
                'editing': False,
                'automation': {
                    'title': title,
                    'instagram_post_id': instagram_post_id,
                    'keywords': keywords,
                    'comment_reply': comment_reply,
                    'followup_dm': followup_dm,
                    'require_follow': require_follow,
                    'follow_request_message': follow_request_message,
                },
            }
            return render(request, self.template_name, context)

        # Create automation
        InstagramAutomation.objects.create(
            user=request.user,
            title=title,
            instagram_post_id=instagram_post_id,
            keywords=keywords,
            comment_reply=comment_reply,
            followup_dm=followup_dm,
            require_follow=require_follow,
            follow_request_message=follow_request_message,
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
        comment_reply = request.POST.get('comment_reply', '').strip()
        followup_dm = request.POST.get('followup_dm', '').strip()
        require_follow = request.POST.get('require_follow') == 'on'
        follow_request_message = request.POST.get('follow_request_message', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        # Validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if len(title) > 100:
            errors.append('Title must be 100 characters or less.')
        if not instagram_post_id:
            errors.append('Please select an Instagram post.')
        if not comment_reply:
            errors.append('Comment reply text is required.')
        if not followup_dm:
            errors.append('Follow-up DM text is required.')
        if require_follow and not follow_request_message:
            errors.append('Follow request message is required when "Require Follow" is enabled.')

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
        automation.comment_reply = comment_reply
        automation.followup_dm = followup_dm
        automation.require_follow = require_follow
        automation.follow_request_message = follow_request_message
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


class AccountAutomationView(IGAutomationFeatureRequiredMixin, LoginRequiredMixin, View):
    """Configure account-level automation settings"""
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
        account_comment_reply = request.POST.get('account_comment_reply', '').strip()
        account_followup_dm = request.POST.get('account_followup_dm', '').strip()
        account_require_follow = request.POST.get('account_require_follow') == 'on'
        account_follow_request_message = request.POST.get('account_follow_request_message', '').strip()

        # Validation
        if account_require_follow and not account_follow_request_message:
            messages.error(request, 'Follow request message is required when "Require Follow" is enabled.')
            context = {'instagram_account': instagram_account}
            return render(request, self.template_name, context)

        # Update account settings
        instagram_account.account_automation_enabled = account_automation_enabled
        instagram_account.account_comment_reply = account_comment_reply
        instagram_account.account_followup_dm = account_followup_dm
        instagram_account.account_require_follow = account_require_follow
        instagram_account.account_follow_request_message = account_follow_request_message
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
            logger.info(f"Instagram webhook received: {json.dumps(payload)[:500]}")

            # Process each entry
            for entry in payload.get('entry', []):
                # The entry 'id' is the Instagram Business Account ID
                ig_business_account_id = entry.get('id', '')

                # Handle comment changes
                for change in entry.get('changes', []):
                    if change.get('field') == 'comments':
                        self.handle_comment(change.get('value', {}), ig_business_account_id)

                # Handle messaging events (for "I Followed" button clicks)
                for messaging in entry.get('messaging', []):
                    if 'postback' in messaging:
                        self.handle_postback(messaging)

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

        if not comment_id:
            logger.warning("Comment event missing comment_id")
            return

        # Check if already processed (deduplication)
        if InstagramCommentEvent.objects.filter(comment_id=comment_id).exists():
            logger.info(f"Comment {comment_id} already processed, skipping")
            return

        # Find the Instagram account this comment belongs to
        logger.info(f"Looking for Instagram account with ID: {ig_business_account_id}")

        # Try matching by instagram_user_id first (for direct IG OAuth)
        # Also try matching by business_account_id in instagram_data (for FB OAuth)
        try:
            instagram_account = InstagramAccount.objects.get(
                instagram_user_id=ig_business_account_id,
                is_active=True
            )
            logger.info(f"Found account by instagram_user_id: {instagram_account.username}")
        except InstagramAccount.DoesNotExist:
            # Try to find by business_account_id stored in instagram_data
            try:
                instagram_account = InstagramAccount.objects.get(
                    instagram_data__business_account_id=ig_business_account_id,
                    is_active=True
                )
                logger.info(f"Found account by business_account_id: {instagram_account.username}")
            except InstagramAccount.DoesNotExist:
                # Log all accounts for debugging
                all_accounts = InstagramAccount.objects.filter(is_active=True).values_list('instagram_user_id', flat=True)
                logger.warning(f"No active Instagram account found for ID: {ig_business_account_id}. Active accounts: {list(all_accounts)}")
                return

        user = instagram_account.user

        # Create event record for tracking
        event = InstagramCommentEvent.objects.create(
            comment_id=comment_id,
            post_id=post_id,
            user=user,
            commenter_username=commenter_username,
            commenter_id=commenter_id,
            comment_text=comment_text,
            status='received'
        )

        # Find matching automation
        automation = None
        comment_reply = None
        followup_dm = None
        require_follow = False
        follow_request_message = None

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
                comment_reply = auto.comment_reply
                followup_dm = auto.followup_dm
                require_follow = auto.require_follow
                follow_request_message = auto.follow_request_message
                break

        # If no post-level automation matched, check account-level
        if not automation and instagram_account.account_automation_enabled:
            comment_reply = instagram_account.account_comment_reply
            followup_dm = instagram_account.account_followup_dm
            require_follow = instagram_account.account_require_follow
            follow_request_message = instagram_account.account_follow_request_message

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

        # Handle follow-up DM with optional follow check
        if followup_dm:
            # Check if follow is required
            if require_follow and follow_request_message:
                # Check if user follows
                is_following = self.check_if_user_follows(
                    commenter_id=commenter_id,
                    ig_business_account_id=instagram_account.instagram_user_id,
                    access_token=instagram_account.access_token
                )

                if not is_following:
                    # User doesn't follow - send follow request message with button
                    try:
                        self.send_dm_with_follow_button(
                            commenter_id=commenter_id,
                            message=follow_request_message,
                            comment_id=comment_id,
                            ig_business_account_id=instagram_account.instagram_user_id,
                            access_token=instagram_account.access_token
                        )
                        # Save pending DM for when they click "I Followed"
                        event.waiting_for_follow = True
                        event.pending_followup_dm = followup_dm
                        event.status = 'waiting_follow'
                        event.save()
                        logger.info(f"Follow request sent for comment {comment_id}")
                        return
                    except Exception as e:
                        logger.error(f"Failed to send follow request for {comment_id}: {str(e)}")
                        event.error_message = f"Follow request failed: {str(e)}"
                        event.save()
                        return

            # User follows (or follow not required) - send DM directly
            try:
                self.send_dm_to_commenter(
                    commenter_id=commenter_id,
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

    def handle_postback(self, messaging_data):
        """Handle postback from quick reply button (e.g., 'I Followed')"""
        sender_id = messaging_data.get('sender', {}).get('id', '')
        recipient_id = messaging_data.get('recipient', {}).get('id', '')
        postback = messaging_data.get('postback', {})
        payload = postback.get('payload', '')

        logger.info(f"Postback received: payload={payload}, sender={sender_id}")

        # Check if this is an "I Followed" postback
        if not payload.startswith('I_FOLLOWED_'):
            return

        # Extract comment_id from payload
        comment_id = payload.replace('I_FOLLOWED_', '')

        try:
            # Find the event waiting for follow confirmation
            event = InstagramCommentEvent.objects.get(
                comment_id=comment_id,
                waiting_for_follow=True
            )
        except InstagramCommentEvent.DoesNotExist:
            logger.warning(f"No waiting event found for comment {comment_id}")
            return

        # Get Instagram account
        try:
            instagram_account = InstagramAccount.objects.get(
                instagram_user_id=recipient_id,
                is_active=True
            )
        except InstagramAccount.DoesNotExist:
            logger.warning(f"No Instagram account found for {recipient_id}")
            return

        # Send the pending follow-up DM
        if event.pending_followup_dm:
            try:
                self.send_dm_to_commenter(
                    commenter_id=sender_id,
                    message=event.pending_followup_dm,
                    ig_business_account_id=instagram_account.instagram_user_id,
                    access_token=instagram_account.access_token
                )
                event.dm_sent = True
                event.waiting_for_follow = False
                event.status = 'completed'
                event.save()
                logger.info(f"Follow-up DM sent after 'I Followed' for comment {comment_id}")
            except Exception as e:
                logger.error(f"Failed to send follow-up DM for {comment_id}: {str(e)}")
                event.error_message = f"Follow-up DM failed: {str(e)}"
                event.save()

    def check_if_user_follows(self, commenter_id, ig_business_account_id, access_token):
        """Check if a user follows the Instagram business account"""
        # Note: Instagram API doesn't have a direct "check follower" endpoint.
        # We use the followers endpoint with a user search.
        # This is a simplified check - for production, consider caching.
        try:
            # Get recent followers and check if commenter is in the list
            # This only checks recent followers due to API limitations
            url = f"https://graph.instagram.com/v21.0/{ig_business_account_id}/followers"
            response = requests.get(
                url,
                params={
                    'access_token': access_token,
                    'limit': 100  # Check recent 100 followers
                },
                timeout=30
            )

            if response.ok:
                data = response.json()
                followers = data.get('data', [])
                follower_ids = [f.get('id') for f in followers]
                return commenter_id in follower_ids

            # If API call fails, assume not following (safer)
            logger.warning(f"Follower check failed: {response.text}")
            return False

        except Exception as e:
            logger.error(f"Error checking follower status: {str(e)}")
            return False

    def send_dm_with_follow_button(self, commenter_id, message, comment_id, ig_business_account_id, access_token):
        """Send a DM with 'I Followed' quick reply button"""
        url = f"https://graph.instagram.com/v21.0/{ig_business_account_id}/messages"

        # Use quick_replies for interactive button
        payload = {
            'recipient': {'id': commenter_id},
            'message': {
                'text': message,
                'quick_replies': [
                    {
                        'content_type': 'text',
                        'title': 'I Followed ✓',
                        'payload': f'I_FOLLOWED_{comment_id}'
                    }
                ]
            },
            'access_token': access_token
        }

        response = requests.post(url, json=payload, timeout=30)

        if not response.ok:
            error = response.json().get('error', {}).get('message', response.text)
            raise Exception(error)

        return response.json()

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

    def send_dm_to_commenter(self, commenter_id, message, ig_business_account_id, access_token):
        """Send a DM to the person who commented"""
        url = f"https://graph.instagram.com/v21.0/{ig_business_account_id}/messages"

        payload = {
            'recipient': {'id': commenter_id},
            'message': {'text': message},
            'access_token': access_token
        }

        response = requests.post(url, json=payload, timeout=30)

        if not response.ok:
            error = response.json().get('error', {}).get('message', response.text)
            raise Exception(error)

        return response.json()
