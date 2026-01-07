import os
import tempfile
import urllib.parse
from datetime import timedelta

import requests
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .models import YouTubeAccount
from core.models import Configuration


YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
]


def get_youtube_config():
    """Get YouTube OAuth configuration from database"""
    return {
        'client_id': Configuration.get_value('youtube_client_id', ''),
        'client_secret': Configuration.get_value('youtube_client_secret', ''),
        'app_root_url': Configuration.get_value('app_root_url', ''),
    }


def get_valid_credentials(youtube_account):
    """Get valid credentials, refreshing if necessary"""
    config = get_youtube_config()

    credentials = Credentials(
        token=youtube_account.access_token,
        refresh_token=youtube_account.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        scopes=YOUTUBE_SCOPES,
    )

    # Refresh if expired or expiring soon
    if youtube_account.needs_token_refresh:
        try:
            credentials.refresh(Request())
            # Update stored tokens
            youtube_account.access_token = credentials.token
            # Make expiry timezone-aware if it's naive (Google API returns naive datetime)
            expiry = credentials.expiry
            if expiry and timezone.is_naive(expiry):
                import datetime
                expiry = expiry.replace(tzinfo=datetime.timezone.utc)
            youtube_account.token_expires_at = expiry
            youtube_account.save(update_fields=['access_token', 'token_expires_at', 'updated_at'])
        except Exception as e:
            raise Exception(f"Failed to refresh token: {str(e)}")

    return credentials


class YouTubeConnectView(LoginRequiredMixin, View):
    """Display YouTube connection status"""
    template_name = 'youtube/connect.html'

    def get(self, request):
        youtube_account = None
        if hasattr(request.user, 'youtube_account'):
            youtube_account = request.user.youtube_account

        config = get_youtube_config()
        is_configured = bool(config['client_id'] and config['client_secret'])

        return render(request, self.template_name, {
            'youtube_account': youtube_account,
            'is_configured': is_configured,
        })


class YouTubeOAuthRedirectView(LoginRequiredMixin, View):
    """Redirect user to Google OAuth for YouTube authorization"""

    def post(self, request):
        config = get_youtube_config()

        if not config['client_id'] or not config['client_secret']:
            messages.error(request, 'YouTube API is not configured. Please contact support.')
            return redirect('youtube_connect')

        redirect_uri = f"{config['app_root_url'].rstrip('/')}/youtube/callback/"

        params = {
            'client_id': config['client_id'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(YOUTUBE_SCOPES),
            'access_type': 'offline',  # Required to get refresh_token
            'prompt': 'consent',  # Force consent to always get refresh_token
            'state': str(request.user.id),  # CSRF protection
        }

        oauth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode(params)
        return redirect(oauth_url)


class YouTubeCallbackView(LoginRequiredMixin, View):
    """Handle OAuth callback from Google"""

    def get(self, request):
        # Validate state parameter
        state = request.GET.get('state')
        if state != str(request.user.id):
            messages.error(request, 'Invalid state parameter. Please try again.')
            return redirect('youtube_connect')

        # Check for errors
        error = request.GET.get('error')
        if error:
            messages.error(request, f'Authorization failed: {error}')
            return redirect('youtube_connect')

        code = request.GET.get('code')
        if not code:
            messages.error(request, 'No authorization code received.')
            return redirect('youtube_connect')

        config = get_youtube_config()
        redirect_uri = f"{config['app_root_url'].rstrip('/')}/youtube/callback/"

        # Exchange code for tokens
        try:
            token_response = requests.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'client_id': config['client_id'],
                    'client_secret': config['client_secret'],
                    'code': code,
                    'grant_type': 'authorization_code',
                    'redirect_uri': redirect_uri,
                }
            )
            token_data = token_response.json()

            if 'error' in token_data:
                messages.error(request, f"Token exchange failed: {token_data.get('error_description', token_data['error'])}")
                return redirect('youtube_connect')

            access_token = token_data['access_token']
            refresh_token = token_data.get('refresh_token')
            expires_in = token_data.get('expires_in', 3600)
            token_expires_at = timezone.now() + timedelta(seconds=expires_in)

            if not refresh_token:
                messages.error(request, 'No refresh token received. Please disconnect and reconnect.')
                return redirect('youtube_connect')

            # Fetch channel info
            credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=config['client_id'],
                client_secret=config['client_secret'],
            )

            youtube = build('youtube', 'v3', credentials=credentials)
            channels_response = youtube.channels().list(
                part='snippet',
                mine=True
            ).execute()

            if not channels_response.get('items'):
                messages.error(request, 'No YouTube channel found for this account.')
                return redirect('youtube_connect')

            channel = channels_response['items'][0]
            channel_id = channel['id']
            channel_title = channel['snippet']['title']

            # Save or update YouTubeAccount
            YouTubeAccount.objects.update_or_create(
                user=request.user,
                defaults={
                    'channel_id': channel_id,
                    'channel_title': channel_title,
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'token_expires_at': token_expires_at,
                    'is_active': True,
                    'youtube_data': {
                        'channel_snippet': channel['snippet'],
                        'connected_at': str(timezone.now()),
                    },
                }
            )

            messages.success(request, f'Successfully connected YouTube channel: {channel_title}')
            return redirect('youtube_connect')

        except Exception as e:
            messages.error(request, f'Failed to connect YouTube: {str(e)}')
            return redirect('youtube_connect')


class YouTubeDisconnectView(LoginRequiredMixin, View):
    """Disconnect YouTube account"""

    def post(self, request):
        if hasattr(request.user, 'youtube_account'):
            request.user.youtube_account.delete()
            messages.success(request, 'YouTube account disconnected.')
        return redirect('youtube_connect')


class YouTubePostView(LoginRequiredMixin, View):
    """Post video to YouTube as a Short"""
    template_name = 'youtube/post.html'

    def get(self, request):
        # Check if YouTube is connected
        if not hasattr(request.user, 'youtube_account') or not request.user.youtube_account.is_connected:
            messages.error(request, 'Please connect your YouTube account first.')
            return redirect('youtube_connect')

        video_url = request.GET.get('video_url', '')
        title = request.GET.get('title', '')
        return_url = request.GET.get('return_url', '/users/dashboard/')

        return render(request, self.template_name, {
            'video_url': video_url,
            'title': title,
            'return_url': return_url,
            'youtube_account': request.user.youtube_account,
        })

    def post(self, request):
        if not hasattr(request.user, 'youtube_account') or not request.user.youtube_account.is_connected:
            messages.error(request, 'Please connect your YouTube account first.')
            return redirect('youtube_connect')

        video_url = request.POST.get('video_url', '')
        title = request.POST.get('title', '')[:100]  # YouTube title max 100 chars
        description = request.POST.get('description', '')
        tags = request.POST.get('tags', '').split(',')
        tags = [tag.strip() for tag in tags if tag.strip()][:500]  # Max 500 tags
        return_url = request.POST.get('return_url', '/users/dashboard/')

        if not video_url:
            messages.error(request, 'No video URL provided.')
            return redirect(return_url)

        youtube_account = request.user.youtube_account

        try:
            # Get valid credentials
            credentials = get_valid_credentials(youtube_account)
            youtube = build('youtube', 'v3', credentials=credentials)

            # Download video to temp file
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_file:
                response = requests.get(video_url, stream=True)
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name

            try:
                # Add #Shorts to description for YouTube Shorts algorithm
                full_description = f"{description}\n\n#Shorts" if description else "#Shorts"

                # Prepare video metadata
                body = {
                    'snippet': {
                        'title': title,
                        'description': full_description,
                        'tags': tags,
                        'categoryId': '27',  # Education category
                    },
                    'status': {
                        'privacyStatus': 'public',
                        'selfDeclaredMadeForKids': False,
                    },
                }

                # Upload video using resumable upload
                media = MediaFileUpload(
                    tmp_path,
                    mimetype='video/mp4',
                    resumable=True,
                    chunksize=1024 * 1024  # 1MB chunks
                )

                insert_request = youtube.videos().insert(
                    part='snippet,status',
                    body=body,
                    media_body=media
                )

                response = None
                while response is None:
                    status, response = insert_request.next_chunk()

                video_id = response['id']
                video_url = f"https://youtube.com/shorts/{video_id}"

                messages.success(request, f'Video uploaded successfully! View it at: {video_url}')

            finally:
                # Clean up temp file
                os.unlink(tmp_path)

        except Exception as e:
            messages.error(request, f'Failed to upload video: {str(e)}')

        return redirect(return_url)
