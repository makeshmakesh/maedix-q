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


class GeneratedVideo(models.Model):
    """Store generated quiz videos for users"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='generated_videos'
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='generated_videos'
    )
    s3_url = models.URLField(max_length=500)
    s3_key = models.CharField(max_length=255)
    filename = models.CharField(max_length=255)
    questions_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quiz.title} - {self.user.email} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

    class Meta:
        ordering = ['-created_at']


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


class BulkVideoJob(models.Model):
    """Tracks bulk video generation and posting jobs"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('partially_completed', 'Partially Completed'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bulk_video_jobs'
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name='bulk_video_jobs'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Platform selection
    post_to_instagram = models.BooleanField(default=False)
    post_to_youtube = models.BooleanField(default=False)

    # Video template (optional)
    template = models.ForeignKey(
        'VideoTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bulk_jobs'
    )

    # Per-question configuration stored as JSON
    # Format: [{"question_id": 1, "reveal_answer": true, "intro_text": "...", "outro_text": "..."}, ...]
    questions_config = models.JSONField(default=list)

    # Progress tracking
    total_questions = models.IntegerField(default=0)
    completed_count = models.IntegerField(default=0)
    current_question_id = models.IntegerField(null=True, blank=True)
    current_step = models.CharField(max_length=50, blank=True)  # 'generating', 'posting_instagram', 'posting_youtube'

    # Results stored as JSON
    # Format: [{"question_id": 1, "video_url": "...", "instagram_posted": true, "youtube_posted": true, "error": null}, ...]
    results = models.JSONField(default=list)

    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bulk Job {self.id} - {self.user.email} - {self.quiz.title}"

    @property
    def progress_percent(self):
        if self.total_questions == 0:
            return 0
        # Each question has up to 3 steps: generate, ig post, yt post
        steps_per_question = 1 + (1 if self.post_to_instagram else 0) + (1 if self.post_to_youtube else 0)
        total_steps = self.total_questions * steps_per_question
        completed_steps = self.completed_count * steps_per_question
        return int((completed_steps / total_steps) * 100)

    class Meta:
        ordering = ['-created_at']


class VideoTemplate(models.Model):
    """Video templates for quiz video generation"""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    preview_image = models.URLField(blank=True)  # S3 URL for preview thumbnail
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)  # Requires Pro+ subscription
    sort_order = models.IntegerField(default=0)

    # All template configuration stored as JSON
    # Structure:
    # {
    #   "colors": {
    #     "bg_color": [18, 18, 18],
    #     "text_color": [255, 255, 255],
    #     "accent_color": [138, 43, 226],
    #     "correct_color": [0, 200, 83],
    #     "wrong_color": [239, 68, 68],
    #     "option_bg": [38, 38, 38],
    #     "option_text": [240, 240, 240],
    #     "timer_bg": [75, 0, 130],
    #     "muted_text": [156, 163, 175],
    #     "card_bg": [28, 28, 30]
    #   }
    # }
    config = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['sort_order', 'name']
