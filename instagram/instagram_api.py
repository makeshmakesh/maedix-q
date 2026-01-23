"""
Instagram Graph API Client for DM Flow Builder

Handles all Instagram API interactions including:
- Replying to comments
- Sending DMs (text, quick replies, media)
- Follower verification via content restriction test
"""

import logging
import requests
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Instagram API version
API_VERSION = "v24.0"
BASE_URL = f"https://graph.instagram.com/{API_VERSION}"


class InstagramAPIError(Exception):
    """Custom exception for Instagram API errors"""
    def __init__(self, message: str, code: Optional[int] = None, response_data: Optional[dict] = None):
        self.message = message
        self.code = code
        self.response_data = response_data or {}
        super().__init__(self.message)

    def is_follower_required_error(self) -> bool:
        """Check if this error indicates the user is not a follower"""
        # Common error codes/messages that indicate follower requirement
        error_lower = self.message.lower()
        if any(term in error_lower for term in ['follower', 'follow', 'permission', 'blocked']):
            return True
        # Instagram error codes that might indicate permission issues
        if self.code in [10, 200, 230, 190]:
            return True
        return False


class InstagramAPIClient:
    """Client for Instagram Graph API interactions"""

    def __init__(self, access_token: str, ig_user_id: str):
        """
        Initialize the API client.

        Args:
            access_token: Instagram Business Account access token
            ig_user_id: Instagram Business Account ID
        """
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.timeout = 30

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None
    ) -> dict:
        """Make an HTTP request to the Instagram API."""
        url = f"{BASE_URL}/{endpoint}"

        default_headers = {}
        if json_data:
            default_headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
            }
        if headers:
            default_headers.update(headers)

        # Add access token to params if not using JSON body with auth header
        if not json_data and params is None:
            params = {}
        if params is not None and 'access_token' not in params and not json_data:
            params['access_token'] = self.access_token

        try:
            response = requests.request(
                method=method,
                url=url,
                data=data,
                params=params,
                json=json_data,
                headers=default_headers if default_headers else None,
                timeout=self.timeout
            )

            response_data = response.json()

            if not response.ok:
                error_info = response_data.get('error', {})
                error_message = error_info.get('message', response.text)
                error_code = error_info.get('code')
                logger.error(f"Instagram API error: {error_message} (code: {error_code})")
                raise InstagramAPIError(
                    message=error_message,
                    code=error_code,
                    response_data=response_data
                )

            return response_data

        except requests.RequestException as e:
            logger.error(f"Request error to Instagram API: {str(e)}")
            raise InstagramAPIError(message=f"Network error: {str(e)}")

    # =========================================================================
    # Comment Operations
    # =========================================================================

    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """
        Reply to an Instagram comment.

        Args:
            comment_id: The ID of the comment to reply to
            message: The reply message text

        Returns:
            API response containing the reply ID
        """
        logger.info(f"Replying to comment {comment_id}")
        return self._make_request(
            method='POST',
            endpoint=f'{comment_id}/replies',
            data={
                'message': message,
                'access_token': self.access_token
            }
        )

    # =========================================================================
    # DM Operations
    # =========================================================================

    def send_dm_to_commenter(self, comment_id: str, message: str, quick_replies: Optional[List[Dict[str, str]]] = None) -> dict:
        """
        Send a DM to someone who commented, using comment_id as recipient reference.
        This is used for the FIRST DM after a comment (initiates the conversation).

        Args:
            comment_id: The comment ID (used to identify the recipient)
            message: The message text to send
            quick_replies: Optional list of quick reply buttons

        Returns:
            API response containing the message ID and recipient IGSID
        """
        logger.info(f"Sending DM to commenter via comment {comment_id}")

        message_payload = {'text': message}

        # Add quick replies if provided
        if quick_replies:
            # Validate quick replies (Instagram limits)
            if len(quick_replies) > 13:
                logger.warning("Too many quick replies, truncating to 13")
                quick_replies = quick_replies[:13]
            for qr in quick_replies:
                if len(qr.get('title', '')) > 20:
                    qr['title'] = qr['title'][:20]
            message_payload['quick_replies'] = quick_replies

        payload = {
            'recipient': {'comment_id': comment_id},
            'message': message_payload,
        }
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
        return self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

    def send_text_dm(self, igsid: str, text: str) -> dict:
        """
        Send a plain text DM to a user by their Instagram-scoped ID.
        Used for follow-up messages after initial conversation is established.

        Args:
            igsid: Instagram-scoped ID of the recipient
            text: Message text to send

        Returns:
            API response
        """
        logger.info(f"Sending text DM to IGSID {igsid}")
        payload = {
            'recipient': {'id': igsid},
            'messaging_type': 'RESPONSE',
            'message': {'text': text},
        }
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
        return self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

    def send_dm_with_quick_replies(
        self,
        igsid: str,
        text: str,
        quick_replies: List[Dict[str, str]]
    ) -> dict:
        """
        Send a DM with quick reply buttons.

        Args:
            igsid: Instagram-scoped ID of the recipient
            text: Message text to display above buttons
            quick_replies: List of quick reply options, each with:
                - content_type: "text"
                - title: Button text (max 20 chars)
                - payload: Identifier string for the option

        Returns:
            API response

        Example quick_replies:
            [
                {"content_type": "text", "title": "Get Link", "payload": "get_link"},
                {"content_type": "text", "title": "Learn More", "payload": "learn_more"}
            ]
        """
        logger.info(f"Sending quick reply DM to IGSID {igsid} with {len(quick_replies)} options")

        # Validate quick replies (Instagram limits)
        if len(quick_replies) > 13:
            logger.warning("Too many quick replies, truncating to 13")
            quick_replies = quick_replies[:13]

        for qr in quick_replies:
            if len(qr.get('title', '')) > 20:
                qr['title'] = qr['title'][:20]

        payload = {
            'recipient': {'id': igsid},
            'messaging_type': 'RESPONSE',
            'message': {
                'text': text,
                'quick_replies': quick_replies
            },
        }
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }
        return self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

    def send_link_dm(self, igsid: str, text: str, url: str) -> dict:
        """
        Send a DM containing a link/URL.
        Note: This is just a text message with a URL included.

        Args:
            igsid: Instagram-scoped ID of the recipient
            text: Message text (should include the URL)
            url: The URL to include (for tracking purposes)

        Returns:
            API response
        """
        # For Instagram, links are just sent as text
        # The text should already contain the URL
        full_text = text if url in text else f"{text}\n{url}"
        return self.send_text_dm(igsid, full_text)

    def send_button_template_dm(
        self,
        igsid: str,
        text: str,
        buttons: List[Dict[str, str]]
    ) -> dict:
        """
        Send a DM with button template (up to 3 buttons).

        Button template allows URL buttons (open web page) and Postback buttons
        (trigger webhook notification).

        Args:
            igsid: Instagram-scoped ID of the recipient
            text: Message text (up to 640 chars) displayed above buttons
            buttons: List of button objects (max 3), each with:
                - type: "web_url" or "postback"
                - title: Button text
                - url: (for web_url) The URL to open
                - payload: (for postback) String sent in webhook

        Returns:
            API response

        Example buttons:
            [
                {"type": "web_url", "title": "Visit Site", "url": "https://example.com"},
                {"type": "postback", "title": "Get Started", "payload": "get_started"}
            ]
        """
        logger.info(f"Sending button template DM to IGSID {igsid} with {len(buttons)} buttons")

        # Validate and format buttons (Instagram limits: max 3 buttons)
        if len(buttons) > 3:
            logger.warning("Too many buttons, truncating to 3")
            buttons = buttons[:3]

        formatted_buttons = []
        for btn in buttons:
            btn_type = btn.get('type', 'postback')
            formatted_btn = {
                'type': btn_type,
                'title': btn.get('title', 'Button')[:20]  # Title limit
            }
            if btn_type == 'web_url':
                formatted_btn['url'] = btn.get('url', '')
            else:  # postback
                formatted_btn['payload'] = btn.get('payload', '')
            formatted_buttons.append(formatted_btn)

        payload = {
            'recipient': {'id': igsid},
            'message': {
                'attachment': {
                    'type': 'template',
                    'payload': {
                        'template_type': 'button',
                        'text': text[:640],  # Text limit
                        'buttons': formatted_buttons
                    }
                }
            }
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

        return self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

    def send_button_template_to_commenter(
        self,
        comment_id: str,
        text: str,
        buttons: List[Dict[str, str]]
    ) -> dict:
        """
        Send a button template DM to someone who commented, using comment_id as recipient.
        This is used for the FIRST DM after a comment (initiates the conversation).

        Args:
            comment_id: The comment ID (used to identify the recipient)
            text: Message text displayed above buttons
            buttons: List of button objects (max 3)

        Returns:
            API response containing the message ID and recipient IGSID
        """
        # Validate and format buttons
        if len(buttons) > 3:
            buttons = buttons[:3]

        formatted_buttons = []
        for btn in buttons:
            btn_type = btn.get('type', 'postback')
            formatted_btn = {
                'type': btn_type,
                'title': btn.get('title', 'Button')[:20]
            }
            if btn_type == 'web_url':
                formatted_btn['url'] = btn.get('url', '')
            else:
                formatted_btn['payload'] = btn.get('payload', '')
            formatted_buttons.append(formatted_btn)

        payload = {
            'recipient': {'comment_id': comment_id},
            'message': {
                'attachment': {
                    'type': 'template',
                    'payload': {
                        'template_type': 'button',
                        'text': text[:640],
                        'buttons': formatted_buttons
                    }
                }
            }
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

        return self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

    def send_media_dm(
        self,
        igsid: str,
        media_url: str,
        media_type: str = 'image',
        text: Optional[str] = None
    ) -> dict:
        """
        Send a DM with media (image or video).

        Args:
            igsid: Instagram-scoped ID of the recipient
            media_url: Public URL of the media file
            media_type: 'image' or 'video'
            text: Optional text to accompany the media

        Returns:
            API response
        """
        logger.info(f"Sending {media_type} DM to IGSID {igsid}")

        payload = {
            'recipient': {'id': igsid},
            'messaging_type': 'RESPONSE',
            'message': {
                'attachment': {
                    'type': media_type,
                    'payload': {
                        'url': media_url
                    }
                }
            },
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json',
        }

        # Send media first
        response = self._make_request(
            method='POST',
            endpoint=f'{self.ig_user_id}/messages',
            json_data=payload,
            headers=headers
        )

        # If there's accompanying text, send it as a follow-up
        if text:
            self.send_text_dm(igsid, text)

        return response

    # =========================================================================
    # User Profile & Follower Verification
    # =========================================================================

    def get_user_profile(self, igsid: str) -> dict:
        """
        Get an Instagram user's profile information.

        IMPORTANT: User consent is required - the user must have sent a message
        first (clicked quick reply, button template, icebreaker, etc.) before
        this API can be called.

        Args:
            igsid: Instagram-scoped ID of the user (from webhook notification)

        Returns:
            User profile dict with fields like:
            - name: User's name (can be null)
            - username: User's Instagram username
            - profile_pic: URL to profile picture (expires in a few days)
            - follower_count: Number of followers
            - is_user_follow_business: True if user follows your account
            - is_business_follow_user: True if you follow the user
            - is_verified_user: True if user has verified account

        Raises:
            InstagramAPIError: If user hasn't consented (no prior interaction)
        """
        logger.info(f"Getting profile info for IGSID {igsid}")

        return self._make_request(
            method='GET',
            endpoint=igsid,
            params={
                'fields': 'name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user,is_verified_user',
                'access_token': self.access_token
            }
        )

    def check_is_follower(self, igsid: str) -> tuple[bool, dict]:
        """
        Check if a user follows your Instagram account.

        Uses the User Profile API to check the is_user_follow_business field.
        Requires user consent (user must have interacted via messaging first).

        Args:
            igsid: Instagram-scoped ID of the user

        Returns:
            Tuple of (is_follower: bool, profile_data: dict)

        Raises:
            InstagramAPIError: If user hasn't consented or other API error
        """
        logger.info(f"Checking follower status for IGSID {igsid}")

        try:
            profile = self.get_user_profile(igsid)
            is_follower = profile.get('is_user_follow_business', False)
            return is_follower, profile
        except InstagramAPIError as e:
            logger.error(f"Error checking follower status: {e}")
            raise

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_user_info(self) -> dict:
        """Get the connected Instagram account's basic info."""
        return self._make_request(
            method='GET',
            endpoint='me',
            params={
                'fields': 'id,username,account_type,profile_picture_url,followers_count',
                'access_token': self.access_token
            }
        )

    def get_media(self, limit: int = 50) -> dict:
        """
        Get the user's recent media posts.

        Args:
            limit: Maximum number of posts to return (default 50)

        Returns:
            API response with media data
        """
        return self._make_request(
            method='GET',
            endpoint=f'{self.ig_user_id}/media',
            params={
                'fields': 'id,media_type,media_url,thumbnail_url,timestamp,caption,permalink',
                'access_token': self.access_token,
                'limit': limit
            }
        )


def get_api_client_for_account(instagram_account) -> InstagramAPIClient:
    """
    Create an InstagramAPIClient for a given InstagramAccount model instance.

    Args:
        instagram_account: InstagramAccount model instance

    Returns:
        Configured InstagramAPIClient

    Raises:
        ValueError: If account is not connected or missing credentials
    """
    if not instagram_account.is_connected:
        raise ValueError("Instagram account is not connected or token expired")

    if not instagram_account.access_token or not instagram_account.instagram_user_id:
        raise ValueError("Instagram account missing required credentials")

    return InstagramAPIClient(
        access_token=instagram_account.access_token,
        ig_user_id=instagram_account.instagram_user_id
    )
