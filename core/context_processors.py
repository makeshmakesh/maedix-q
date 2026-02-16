from django.utils import timezone

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

    # Add subscription expiry warning for non-staff, non-free active subscriptions
    if request.user.is_authenticated and not request.user.is_staff:
        try:
            from .subscription_utils import get_user_subscription
            subscription = get_user_subscription(request.user)
            if (subscription and subscription.plan
                    and subscription.status == 'active'
                    and subscription.end_date
                    and subscription.plan.name != 'Free'):
                days_left = (subscription.end_date - timezone.now()).days
                if 0 <= days_left <= 5:
                    s = '' if days_left == 1 else 's'
                    active_banners.insert(0, {
                        'id': f'sub_expiry_{days_left}',
                        'title': 'Subscription Expiring',
                        'message': f'Your subscription ends in {days_left} day{s}. Renew now to avoid losing access.',
                        'banner_type': 'warning',
                        'link_url': '/pricing/',
                        'link_text': 'Renew Now',
                        'display_seconds': 0,
                        'is_dismissible': True,
                    })
        except Exception:
            pass

    return {'banners': active_banners}
