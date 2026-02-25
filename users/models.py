import re
import random
import hashlib
from django.db import models
from django.db.models import F
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.utils import timezone
from datetime import timedelta
from .managers import CustomUserManager


username_validator = RegexValidator(
    regex=r'^[a-zA-Z0-9_]+$',
    message='Username may only contain letters, numbers, and underscores.',
)


def generate_unique_username(email):
    """Generate a unique username from an email address."""
    prefix = email.split('@')[0]
    # Strip non-alphanumeric chars (keep underscores), lowercase
    username = re.sub(r'[^a-zA-Z0-9_]', '', prefix).lower()
    # Ensure minimum length
    if len(username) < 3:
        username = username + '_user'
    # Truncate to fit max_length with room for suffix
    username = username[:24]

    if not CustomUser.objects.filter(username__iexact=username).exists():
        return username

    # Append random digits until unique
    for _ in range(100):
        suffix = random.randint(100, 9999)
        candidate = f"{username}_{suffix}"
        if not CustomUser.objects.filter(username__iexact=candidate).exists():
            return candidate

    # Fallback: use timestamp
    return f"{username}_{int(timezone.now().timestamp())}"


def hash_ip(ip_address):
    """SHA256 hash an IP address for privacy-safe storage."""
    return hashlib.sha256(ip_address.encode()).hexdigest()


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Custom user model with email as the primary identifier"""
    email = models.EmailField(unique=True)
    username = models.CharField(
        max_length=30,
        unique=True,
        validators=[username_validator],
        help_text='Letters, numbers, and underscores only. 3-30 characters.',
    )
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_short_name(self):
        return self.first_name or self.email.split('@')[0]


class UserProfile(models.Model):
    """Extended user profile information"""
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    bio = models.TextField(max_length=500, blank=True)
    location = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    github_username = models.CharField(max_length=39, blank=True)
    linkedin_url = models.URLField(blank=True)
    twitter_handle = models.CharField(max_length=15, blank=True)
    skills = models.JSONField(default=list)  # List of skill tags
    credits = models.FloatField(default=0.0)  # AI credits balance
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.email}"

    def has_credits(self, required: float = 1.0) -> bool:
        """Check if user has enough credits"""
        return self.credits >= required

    def deduct_credits(self, amount: float = 1.0) -> bool:
        """Deduct credits from user balance"""
        if self.credits >= amount:
            self.credits = round(self.credits - amount, 4)  # Avoid floating point issues
            self.save(update_fields=['credits', 'updated_at'])
            return True
        return False

    def add_credits(self, amount: float) -> None:
        """Add credits to user balance"""
        self.credits = round(self.credits + amount, 4)  # Avoid floating point issues
        self.save(update_fields=['credits', 'updated_at'])

    def get_credits_balance(self) -> float:
        """Get current credits balance"""
        return round(self.credits, 2)


class UserStats(models.Model):
    """User statistics and gamification data"""
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='stats'
    )
    total_quizzes_taken = models.IntegerField(default=0)
    total_quizzes_passed = models.IntegerField(default=0)
    total_questions_answered = models.IntegerField(default=0)
    total_correct_answers = models.IntegerField(default=0)
    xp_points = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_quiz_date = models.DateField(null=True, blank=True)
    rank = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Stats: {self.user.email}"

    @property
    def accuracy(self):
        if self.total_questions_answered == 0:
            return 0
        return round((self.total_correct_answers / self.total_questions_answered) * 100, 1)

    @property
    def pass_rate(self):
        if self.total_quizzes_taken == 0:
            return 0
        return round((self.total_quizzes_passed / self.total_quizzes_taken) * 100, 1)

    class Meta:
        verbose_name_plural = 'User Stats'


class EmailOTP(models.Model):
    """Store OTP for email verification during signup"""
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='email_otps'
    )
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"OTP for {self.user.email}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_expired and not self.is_verified

    @classmethod
    def generate_otp(cls):
        """Generate a 6-digit OTP"""
        return ''.join([str(random.randint(0, 9)) for _ in range(6)])

    @classmethod
    def create_for_user(cls, user):
        """Create a new OTP for user, invalidating any previous ones"""
        # Delete any existing unverified OTPs for this user
        cls.objects.filter(user=user, is_verified=False).delete()
        # Create new OTP
        otp = cls.generate_otp()
        return cls.objects.create(user=user, otp=otp)

    class Meta:
        verbose_name = 'Email OTP'
        verbose_name_plural = 'Email OTPs'
        ordering = ['-created_at']


class UserAcquisition(models.Model):
    """Tracks how a user discovered and arrived at the platform."""
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='acquisition'
    )
    # UTM parameters
    utm_source = models.CharField(max_length=200, blank=True)
    utm_medium = models.CharField(max_length=200, blank=True)
    utm_campaign = models.CharField(max_length=200, blank=True)
    utm_term = models.CharField(max_length=200, blank=True)
    utm_content = models.CharField(max_length=200, blank=True)
    # HTTP referrer
    referrer = models.URLField(max_length=2000, blank=True)
    referrer_domain = models.CharField(max_length=253, blank=True)
    # First page they landed on
    landing_page = models.CharField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        source = self.utm_source or self.referrer_domain or 'direct'
        return f"{self.user.email} — {source}"

    @property
    def source_display(self):
        """Human-readable acquisition source."""
        if self.utm_source:
            return self.utm_source
        if self.referrer_domain:
            return self.referrer_domain
        return 'Direct'

    class Meta:
        verbose_name = 'User Acquisition'
        verbose_name_plural = 'User Acquisitions'


class ProfileLink(models.Model):
    """A link on a user's public profile page (Linktree-style)."""
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='profile_links'
    )
    title = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    icon = models.CharField(max_length=50, blank=True, help_text='Bootstrap icon class, e.g. bi-globe')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    click_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.user.username})"

    def increment_clicks(self, count=1):
        """Increment click counter atomically."""
        ProfileLink.objects.filter(pk=self.pk).update(
            click_count=F('click_count') + count
        )

    class Meta:
        ordering = ['order', 'created_at']


class ProfilePageView(models.Model):
    """Tracks visits to a user's public profile page."""
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='profile_page_views'
    )
    ip_hash = models.CharField(max_length=64)
    referrer = models.URLField(blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    viewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"View: {self.user.username} at {self.viewed_at}"


class ProfileLinkClick(models.Model):
    """Tracks clicks on individual profile links."""
    link = models.ForeignKey(
        ProfileLink,
        on_delete=models.CASCADE,
        related_name='clicks'
    )
    ip_hash = models.CharField(max_length=64)
    referrer = models.URLField(blank=True)
    clicked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Click: {self.link.title} at {self.clicked_at}"
