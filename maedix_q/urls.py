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
    ComparisonSitemap,
    BlogPostSitemap,
    BlogCategorySitemap,
)
from core.views import robots_txt, llms_txt, ads_txt
from users.views import PublicProfileView, ProfileLinkClickView

sitemaps = {
    'static': StaticSitemap,
    'comparisons': ComparisonSitemap,
    'blog_posts': BlogPostSitemap,
    'blog_categories': BlogCategorySitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('llms.txt', llms_txt, name='llms_txt'),
    path('ads.txt', ads_txt, name='ads_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('ckeditor5/', include('django_ckeditor_5.urls')),
    path('', include('core.urls')),
    path('users/', include('users.urls')),
    path('instagram/', include('instagram.urls')),
    path('youtube/', include('youtube.urls')),
    path('blog/', include('blog.urls')),

    # Public profile routes (must be LAST to avoid collisions)
    path('@<str:username>/', PublicProfileView.as_view(), name='public_profile'),
    path('@<str:username>/go/<int:link_id>/', ProfileLinkClickView.as_view(), name='profile_link_click'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
