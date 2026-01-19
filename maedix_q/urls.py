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
    QuizSitemap,
    CategorySitemap,
    TopicSitemap,
    QuizHomeSitemap,
)
from core.views import robots_txt

sitemaps = {
    'static': StaticSitemap,
    'quiz_home': QuizHomeSitemap,
    'quizzes': QuizSitemap,
    'categories': CategorySitemap,
    'topics': TopicSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('', include('core.urls')),
    path('users/', include('users.urls')),
    path('quiz/', include('quiz.urls')),
    path('instagram/', include('instagram.urls')),
    path('youtube/', include('youtube.urls')),
    path('roleplay/', include('roleplay.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
