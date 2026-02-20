from django import template
from blog.models import BlogPost

register = template.Library()


@register.simple_tag
def latest_blog_posts(count=3):
    return BlogPost.objects.filter(is_published=True).order_by('-published_at', '-created_at')[:count]
