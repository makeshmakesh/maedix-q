from django.db import models
from django.conf import settings
from django.utils import timezone


class YouTubeAccount(models.Model):
    """Stores YouTube channel connection for a user"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='youtube_account'
    )

    # YouTube Channel Details
    channel_id = models.CharField(max_length=255, blank=True, null=True)
    channel_title = models.CharField(max_length=255, blank=True, null=True)

    # OAuth Credentials
    access_token = models.TextField(blank=True, null=True)
    refresh_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)

    # Additional data stored as JSON
    youtube_data = models.JSONField(default=dict, blank=True)

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.channel_title or f"YouTube - User {self.user_id}"

    @property
    def is_connected(self):
        """Check if YouTube is connected and has valid refresh token"""
        if not self.access_token or not self.refresh_token:
            return False
        return self.is_active

    @property
    def needs_token_refresh(self):
        """Check if access token needs refresh"""
        if not self.token_expires_at:
            return True
        # Refresh if expiring within 5 minutes
        return self.token_expires_at <= timezone.now() + timezone.timedelta(minutes=5)

    class Meta:
        verbose_name = 'YouTube Account'
        verbose_name_plural = 'YouTube Accounts'
