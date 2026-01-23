from .models import Configuration


def site_settings(request):
    """Add site-wide settings to template context"""
    return {
        'favicon_url': Configuration.get_value('favicon_url', ''),
    }
