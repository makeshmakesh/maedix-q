from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from quiz.models import Quiz, Category, Topic


class StaticSitemap(Sitemap):
    """Sitemap for static pages like home, about, pricing, etc."""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['home', 'about', 'pricing', 'contact', 'terms', 'privacy_policy', 'refund_policy']

    def location(self, item):
        return reverse(item)


class QuizSitemap(Sitemap):
    """Sitemap for published and approved quizzes"""
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Quiz.objects.filter(
            status='approved',
            is_published=True
        ).select_related('category')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('quiz_detail', kwargs={'slug': obj.slug})


class CategorySitemap(Sitemap):
    """Sitemap for quiz categories"""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.filter(is_active=True)

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('category_detail', kwargs={'slug': obj.slug})


class TopicSitemap(Sitemap):
    """Sitemap for published topics"""
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Topic.objects.filter(status='published')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('topic_detail', kwargs={'slug': obj.slug})


class QuizHomeSitemap(Sitemap):
    """Sitemap for main quiz-related pages"""
    priority = 0.9
    changefreq = 'daily'

    def items(self):
        return ['quiz_home', 'categories', 'topics_home']

    def location(self, item):
        return reverse(item)
