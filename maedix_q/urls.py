"""
URL configuration for maedix_q project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from core.sitemaps import (
    StaticSitemap,
    BlogPostSitemap,
    BlogCategorySitemap,
)
from core.views import robots_txt

sitemaps = {
    'static': StaticSitemap,
    'blog_posts': BlogPostSitemap,
    'blog_categories': BlogCategorySitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
    path('', include('core.urls')),
    path('users/', include('users.urls')),
    path('quiz/', include('quiz.urls')),
    path('instagram/', include('instagram.urls')),
    path('youtube/', include('youtube.urls')),
    path('roleplay/', include('roleplay.urls')),
    path('games/', include('games.urls')),
    path('blog/', include('blog.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
