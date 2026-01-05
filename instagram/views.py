import requests
import urllib.parse
from datetime import datetime, timedelta
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.utils import timezone
from .models import InstagramAccount
from core.models import Configuration


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
            instagram_account, created = InstagramAccount.objects.update_or_create(
                user=request.user,
                defaults={
                    "instagram_user_id": user_info.get("id", ""),
                    "username": user_info.get("username", ""),
                    "access_token": access_token,
                    "token_expires_at": token_expires_at,
                    "is_active": True,
                    "instagram_data": {
                        "user_info": user_info,
                        "connected_at": str(timezone.now()),
                    },
                },
            )

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
