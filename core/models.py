from django.db import models
from django.conf import settings


class Configuration(models.Model):
    """Key-value configuration storage"""
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    @staticmethod
    def get_value(key, default=None):
        """Get configuration value by key"""
        try:
            return Configuration.objects.get(key=key).value
        except Configuration.DoesNotExist:
            return default

    @staticmethod
    def set_value(key, value):
        """Set configuration value"""
        obj, _ = Configuration.objects.update_or_create(
            key=key, defaults={"value": value}
        )
        return obj

    class Meta:
        ordering = ['key']


class Plan(models.Model):
    """Pricing plans"""
    PLAN_TYPES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('enterprise', 'Enterprise'),
    ]

    name = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES, default='free')
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_yearly = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Country-based pricing: {"US": {"monthly": 5.99, "yearly": 59.99, "currency": "USD", "symbol": "$"}, ...}
    pricing_data = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    # Features structure: [{"code": "video_gen", "description": "...", "limit": 10}, ...]
    features = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def has_feature(self, code):
        """Check if plan has a specific feature"""
        for feature in self.features:
            if feature.get('code') == code:
                return True
        return False

    def get_feature(self, code):
        """Get feature details by code"""
        for feature in self.features:
            if feature.get('code') == code:
                return feature
        return None

    def get_feature_limit(self, code, default=0):
        """Get the limit for a specific feature"""
        feature = self.get_feature(code)
        if feature:
            return feature.get('limit', default)
        return default

    def get_pricing_for_country(self, country_code):
        """
        Get pricing for a specific country.
        Returns dict with monthly, yearly, currency, symbol.
        Falls back to INR pricing if country not found.
        """
        if country_code and country_code in self.pricing_data:
            return self.pricing_data[country_code]
        # Default to INR pricing
        return {
            'monthly': float(self.price_monthly),
            'yearly': float(self.price_yearly),
            'currency': 'INR',
            'symbol': '₹'
        }

    class Meta:
        ordering = ['order', 'price_monthly']


class Subscription(models.Model):
    """User subscriptions to plans"""
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('trialing', 'Trialing'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    is_yearly = models.BooleanField(default=False)
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)
    # Usage tracking
    usage_data = models.JSONField(default=dict)  # {"video_gen": 5, "quiz_create": 10}
    last_reset_date = models.DateTimeField(null=True, blank=True)
    next_reset_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.plan.name}"

    def is_active(self):
        """Check if subscription is currently active"""
        from django.utils import timezone
        if self.status != 'active':
            return False
        if self.end_date and self.end_date < timezone.now():
            return False
        return True

    def get_usage(self, feature_code):
        """Get current usage for a feature"""
        return self.usage_data.get(feature_code, 0)

    def increment_usage(self, feature_code, amount=1):
        """Increment usage for a feature"""
        current = self.usage_data.get(feature_code, 0)
        self.usage_data[feature_code] = current + amount
        self.save(update_fields=['usage_data', 'updated_at'])

    def can_use_feature(self, feature_code):
        """Check if user can use a feature (within limit)"""
        if not self.is_active():
            return False
        feature = self.plan.get_feature(feature_code)
        if not feature:
            return False
        limit = feature.get('limit')
        if limit is None:  # Unlimited
            return True
        return self.get_usage(feature_code) < limit

    def get_remaining(self, feature_code):
        """Get remaining usage for a feature"""
        feature = self.plan.get_feature(feature_code)
        if not feature:
            return 0
        limit = feature.get('limit')
        if limit is None:
            return float('inf')
        return max(0, limit - self.get_usage(feature_code))

    class Meta:
        ordering = ['-created_at']


class Transaction(models.Model):
    """Payment transactions"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    razorpay_order_id = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.amount} {self.currency}"

    class Meta:
        ordering = ['-created_at']


class ContactMessage(models.Model):
    """Contact form submissions"""
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.subject}"

    class Meta:
        ordering = ['-created_at']


class Banner(models.Model):
    """Site-wide rotating banners for announcements"""
    BANNER_TYPES = [
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('promo', 'Promotional'),
    ]

    title = models.CharField(max_length=200)
    message = models.TextField()
    banner_type = models.CharField(max_length=20, choices=BANNER_TYPES, default='info')
    link_url = models.URLField(blank=True, help_text="Optional link for CTA button")
    link_text = models.CharField(max_length=50, blank=True, help_text="Button text (e.g., 'Learn More')")
    display_seconds = models.PositiveIntegerField(default=5, help_text="Seconds to display before switching to next banner")
    is_active = models.BooleanField(default=True)
    is_dismissible = models.BooleanField(default=True, help_text="Allow users to close the banner")
    order = models.IntegerField(default=0, help_text="Lower numbers appear first")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    @classmethod
    def get_active_banners(cls):
        """Get all currently active banners ordered by priority"""
        return cls.objects.filter(is_active=True).order_by('order', '-created_at')

    class Meta:
        ordering = ['order', '-created_at']
