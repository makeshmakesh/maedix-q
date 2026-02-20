from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Category(models.Model):
    """Blog categories for organizing posts"""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('blog:category', kwargs={'category_slug': self.slug})


class BlogPost(models.Model):
    """Blog posts with HTML content"""
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=200)

    # Content - stores HTML
    excerpt = models.TextField(
        help_text="Short summary shown in blog list (plain text, 150-200 chars)"
    )
    content = models.TextField(
        help_text="Full post content - HTML allowed"
    )

    # SEO
    meta_description = models.CharField(
        max_length=160,
        help_text="SEO meta description (max 160 chars)"
    )
    meta_keywords = models.CharField(
        max_length=255,
        blank=True,
        help_text="Comma-separated keywords for SEO"
    )

    # Media
    featured_image = models.ImageField(
        upload_to='blog/images/',
        blank=True,
        null=True,
        help_text="Featured image (recommended: 1200x630px for social sharing)"
    )
    featured_image_alt = models.CharField(
        max_length=200,
        blank=True,
        help_text="Alt text for featured image"
    )

    # Organization
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts'
    )

    # Publishing
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        # Auto-set published_at when first published
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('blog:post_detail', kwargs={'slug': self.slug})

    @property
    def reading_time(self):
        """Estimate reading time in minutes"""
        word_count = len(self.content.split())
        return max(1, round(word_count / 200))
