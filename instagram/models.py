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

    # Account-level automation settings (fallback for posts without specific automation)
    account_automation_enabled = models.BooleanField(
        default=False,
        help_text="Enable automation for comments on posts without specific automation rules"
    )
    account_comment_reply = models.TextField(
        blank=True,
        help_text="Default reply to comments (used when no post-level automation matches)"
    )
    account_followup_dm = models.TextField(
        blank=True,
        help_text="Default follow-up DM to send after comment reply"
    )

    # Follow-check settings for account-level automation
    account_require_follow = models.BooleanField(
        default=False,
        help_text="Require user to follow before sending follow-up DM"
    )
    account_follow_request_message = models.TextField(
        blank=True,
        help_text="Message to send when user is not following (include call-to-action to follow)"
    )

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


class InstagramAutomation(models.Model):
    """Post-level automation configuration for Instagram comment replies"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instagram_automations'
    )

    # Automation details
    title = models.CharField(
        max_length=100,
        help_text="Name for this automation (e.g., 'Python Quiz Promo')"
    )
    instagram_post_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Instagram post ID (optional - leave blank for keyword-only matching)"
    )
    keywords = models.TextField(
        help_text="Comma-separated keywords to trigger this automation (e.g., 'link, send, dm')"
    )
    comment_reply = models.TextField(
        help_text="Reply text to post as a comment response"
    )
    followup_dm = models.TextField(
        help_text="Follow-up DM text to send to the commenter"
    )

    # Follow-check settings
    require_follow = models.BooleanField(
        default=False,
        help_text="Require user to follow before sending follow-up DM"
    )
    follow_request_message = models.TextField(
        blank=True,
        help_text="Message to send when user is not following (include call-to-action to follow)"
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.user.email})"

    def get_keywords_list(self):
        """Return keywords as a list"""
        return [kw.strip().lower() for kw in self.keywords.split(',') if kw.strip()]

    def matches_comment(self, comment_text):
        """Check if comment text matches any of the keywords (empty keywords = match all)"""
        keywords = self.get_keywords_list()
        # If no keywords specified, match all comments
        if not keywords:
            return True
        comment_lower = comment_text.lower()
        return any(keyword in comment_lower for keyword in keywords)

    class Meta:
        verbose_name = "Instagram Automation"
        verbose_name_plural = "Instagram Automations"
        ordering = ['-created_at']


class InstagramCommentEvent(models.Model):
    """Track processed Instagram comment events for deduplication"""
    comment_id = models.CharField(max_length=255, unique=True, db_index=True)
    post_id = models.CharField(max_length=255, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='instagram_comment_events'
    )
    automation = models.ForeignKey(
        InstagramAutomation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='comment_events'
    )

    # Event details
    commenter_username = models.CharField(max_length=255, blank=True)
    commenter_id = models.CharField(max_length=255, blank=True)
    comment_text = models.TextField(blank=True)

    # Response tracking
    comment_replied = models.BooleanField(default=False)
    dm_sent = models.BooleanField(default=False)
    reply_text = models.TextField(blank=True)
    dm_text = models.TextField(blank=True)

    # Follow-check tracking
    waiting_for_follow = models.BooleanField(
        default=False,
        help_text="User hasn't followed yet, waiting for confirmation"
    )
    pending_followup_dm = models.TextField(
        blank=True,
        help_text="DM text to send after user confirms they followed"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('received', 'Received'),
            ('processed', 'Processed'),
            ('replied', 'Replied'),
            ('waiting_follow', 'Waiting for Follow'),
            ('dm_sent', 'DM Sent'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('skipped', 'Skipped'),
        ],
        default='received'
    )
    error_message = models.TextField(blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Comment {self.comment_id} - {self.status}"

    class Meta:
        verbose_name = "Instagram Comment Event"
        verbose_name_plural = "Instagram Comment Events"
        ordering = ['-created_at']
