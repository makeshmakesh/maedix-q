from django.db import models
from django.conf import settings


class InstagramAccount(models.Model):
    """Stores Instagram Business account connection for a user"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instagram_account'
    )

    # Instagram Business Account Details
    instagram_user_id = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    access_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)

    # Additional data stored as JSON
    instagram_data = models.JSONField(default=dict, blank=True)

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"@{self.username}" if self.username else f"User {self.user_id}"

    @property
    def is_connected(self):
        """Check if Instagram is connected and token is valid"""
        from django.utils import timezone
        if not self.access_token:
            return False
        if self.token_expires_at and self.token_expires_at < timezone.now():
            return False
        return True

    class Meta:
        verbose_name = "Instagram Account"
        verbose_name_plural = "Instagram Accounts"
