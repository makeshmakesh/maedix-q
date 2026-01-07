import uuid
from django.db import models
from django.conf import settings


# Voice choices for OpenAI Realtime API
VOICE_CHOICES = [
    ('alloy', 'Alloy'),
    ('echo', 'Echo'),
    ('fable', 'Fable'),
    ('onyx', 'Onyx'),
    ('nova', 'Nova'),
    ('shimmer', 'Shimmer'),
]

# Category choices for bots
CATEGORY_CHOICES = [
    ('interview', 'Interview Prep'),
    ('language', 'Language Learning'),
    ('education', 'Education'),
    ('therapy', 'Therapy & Counseling'),
    ('coaching', 'Life Coaching'),
    ('roleplay', 'General Roleplay'),
    ('other', 'Other'),
]

# Session status choices
SESSION_STATUS_CHOICES = [
    ('in_progress', 'In Progress'),
    ('completed', 'Completed'),
    ('error', 'Error'),
]

# Transaction status choices
TRANSACTION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('refunded', 'Refunded'),
]


class RolePlayBot(models.Model):
    """AI Bot for voice roleplay - Admin created only"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField()
    avatar_url = models.URLField(blank=True)
    system_prompt = models.TextField(help_text="Instructions for the AI model")
    voice = models.CharField(max_length=20, choices=VOICE_CHOICES, default='alloy')
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='roleplay')
    custom_configuration = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional configuration like temperature, etc."
    )
    required_credits = models.IntegerField(default=10, help_text="Credits required per minute")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, help_text="Display order (lower = first)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Roleplay Bot'
        verbose_name_plural = 'Roleplay Bots'

    def __str__(self):
        return self.name


class RoleplaySession(models.Model):
    """Individual roleplay conversation record"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='roleplay_sessions'
    )
    bot = models.ForeignKey(
        RolePlayBot,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    status = models.CharField(
        max_length=20,
        choices=SESSION_STATUS_CHOICES,
        default='in_progress'
    )
    transcript = models.TextField(blank=True, help_text="Conversation transcript")
    duration_seconds = models.IntegerField(default=0)
    credits_used = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Roleplay Session'
        verbose_name_plural = 'Roleplay Sessions'

    def __str__(self):
        return f"{self.user.email} - {self.bot.name} ({self.started_at.strftime('%Y-%m-%d %H:%M')})"


class CreditTransaction(models.Model):
    """Track credit purchases"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='credit_transactions'
    )
    credits = models.IntegerField(help_text="Number of credits purchased")
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Payment amount")
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(
        max_length=20,
        choices=TRANSACTION_STATUS_CHOICES,
        default='pending'
    )
    razorpay_order_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Credit Transaction'
        verbose_name_plural = 'Credit Transactions'

    def __str__(self):
        return f"{self.user.email} - {self.credits} credits ({self.status})"
