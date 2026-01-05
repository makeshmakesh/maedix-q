import random
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils import timezone
from datetime import timedelta
from .managers import CustomUserManager


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Custom user model with email as the primary identifier"""
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=50, blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.email}"


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
