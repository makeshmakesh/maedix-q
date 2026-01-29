from .models import Configuration, Banner


def site_settings(request):
    """Add site-wide settings to template context"""
    return {
        'favicon_url': Configuration.get_value('favicon_url', ''),
    }


def user_features(request):
    """Add user feature flags to template context for navbar and other global templates"""
    features = {
        'ai_social_agent': False,
        'ig_flow_builder': False,
    }

    if not request.user.is_authenticated:
        return {'user_features': features}

    # Staff users have all features
    if request.user.is_staff:
        return {'user_features': {k: True for k in features}}

    # Check subscription
    try:
        from .subscription_utils import get_user_subscription
        subscription = get_user_subscription(request.user)
        if subscription and subscription.plan:
            features['ai_social_agent'] = subscription.plan.has_feature('ai_social_agent')
            features['ig_flow_builder'] = subscription.plan.has_feature('ig_flow_builder')
    except Exception:
        pass

    return {'user_features': features}


def banners(request):
    """Add active banners to template context"""
    active_banners = list(Banner.get_active_banners().values(
        'id', 'title', 'message', 'banner_type', 'link_url',
        'link_text', 'display_seconds', 'is_dismissible'
    ))
    return {'banners': active_banners}
