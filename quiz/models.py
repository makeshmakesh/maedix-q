from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Category(models.Model):
    """Quiz categories (Python, AI, Django, etc.)"""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True)  # Icon class name
    color = models.CharField(max_length=20, default='#6366f1')  # Hex color
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories'
    )
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def quiz_count(self):
        return self.quizzes.filter(is_published=True).count()

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']


class Quiz(models.Model):
    """Quiz definition"""
    DIFFICULTY_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='quizzes'
    )
    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
        default='beginner'
    )
    time_limit = models.IntegerField(default=600, help_text='Time limit in seconds')
    pass_percentage = models.IntegerField(default=70)
    xp_reward = models.IntegerField(default=10)
    thumbnail = models.ImageField(upload_to='quiz_thumbnails/', blank=True, null=True)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)

    # Approval workflow
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_quizzes'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_quizzes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def total_attempts(self):
        return self.attempts.count()

    @property
    def can_be_edited(self):
        """Check if quiz can be edited (not approved)"""
        return self.status != 'approved'

    @property
    def can_be_deleted(self):
        """Check if quiz can be deleted (not approved)"""
        return self.status != 'approved'

    @property
    def is_pending(self):
        return self.status == 'pending'

    @property
    def is_approved(self):
        return self.status == 'approved'

    class Meta:
        verbose_name_plural = 'Quizzes'
        ordering = ['-created_at']


class Question(models.Model):
    """Quiz questions"""
    QUESTION_TYPES = [
        ('single', 'Single Choice'),
        ('multiple', 'Multiple Choice'),
        ('true_false', 'True/False'),
        ('code', 'Code Snippet'),
    ]

    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='questions'
    )
    text = models.TextField()
    question_type = models.CharField(
        max_length=20,
        choices=QUESTION_TYPES,
        default='single'
    )
    code_snippet = models.TextField(blank=True, help_text='Code to display with question')
    code_language = models.CharField(max_length=20, blank=True, default='python')
    explanation = models.TextField(blank=True, help_text='Explanation shown after answer')
    order = models.IntegerField(default=0)
    points = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.quiz.title} - Q{self.order}"

    class Meta:
        ordering = ['order']


class Option(models.Model):
    """Question answer options"""
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='options'
    )
    text = models.TextField()
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.question} - Option {self.order}"

    class Meta:
        ordering = ['order']


class QuizAttempt(models.Model):
    """User's quiz attempt session"""
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    score = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)
    percentage = models.FloatField(default=0)
    passed = models.BooleanField(default=False)
    time_taken = models.IntegerField(default=0, help_text='Time taken in seconds')
    xp_earned = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.email} - {self.quiz.title}"

    class Meta:
        ordering = ['-started_at']


class QuestionAnswer(models.Model):
    """User's answer for a specific question in an attempt"""
    attempt = models.ForeignKey(
        QuizAttempt,
        on_delete=models.CASCADE,
        related_name='answers'
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name='user_answers'
    )
    selected_options = models.ManyToManyField(Option, blank=True)
    is_correct = models.BooleanField(default=False)
    points_earned = models.IntegerField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.attempt} - {self.question}"

    class Meta:
        unique_together = ['attempt', 'question']


class Leaderboard(models.Model):
    """Leaderboard entries"""
    PERIOD_CHOICES = [
        ('all_time', 'All Time'),
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('daily', 'Daily'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='leaderboard_entries'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='leaderboard_entries'
    )
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='all_time')
    score = models.IntegerField(default=0)
    quizzes_completed = models.IntegerField(default=0)
    rank = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        category_name = self.category.name if self.category else 'Overall'
        return f"{self.user.email} - {category_name} - Rank {self.rank}"

    class Meta:
        unique_together = ['user', 'category', 'period']
        ordering = ['rank']
