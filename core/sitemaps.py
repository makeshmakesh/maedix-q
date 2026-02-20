from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from blog.models import BlogPost, Category as BlogCategory


class StaticSitemap(Sitemap):
    """Sitemap for static pages - Instagram automation focused"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return [
            'home',
            'instagram_automation_landing',
            'about',
            'pricing',
            'contact',
            'terms',
            'privacy_policy',
            'refund_policy',
        ]

    def location(self, item):
        return reverse(item)


class ComparisonSitemap(Sitemap):
    """Sitemap for competitor comparison pages"""
    priority = 0.7
    changefreq = 'monthly'

    def items(self):
        return ['manychat', 'linkdm', 'replyrush']

    def location(self, item):
        return reverse('comparison', kwargs={'competitor_slug': item})


class BlogPostSitemap(Sitemap):
    """Sitemap for published blog posts"""
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return BlogPost.objects.filter(is_published=True)

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return obj.get_absolute_url()


class BlogCategorySitemap(Sitemap):
    """Sitemap for blog categories"""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return BlogCategory.objects.all()

    def location(self, obj):
        return obj.get_absolute_url()
