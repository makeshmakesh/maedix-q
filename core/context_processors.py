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
        'profile_links': False,
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
            features['profile_links'] = subscription.plan.has_feature('profile_links')
    except Exception:
        pass

    return {'user_features': features}


def banners(request):
    """Add active banners and popup banners to template context"""
    fields = (
        'id', 'title', 'message', 'banner_type', 'display_mode',
        'link_url', 'link_text', 'image_url', 'display_seconds',
        'is_dismissible', 'requires_auth',
    )
    is_authed = request.user.is_authenticated
    all_banners = [
        b for b in Banner.get_active_banners().values(*fields)
        if not b['requires_auth'] or is_authed
    ]

    top_banners = [b for b in all_banners if b['display_mode'] in ('banner', 'both')]
    popup_banners = [b for b in all_banners if b['display_mode'] in ('popup', 'both')]

    # Add subscription expiry warning for non-staff, non-free active subscriptions
    if request.user.is_authenticated:
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
                    top_banners.insert(0, {
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

        # Add Instagram token expiry warning
        try:
            from instagram.models import InstagramAccount
            ig_account = InstagramAccount.objects.filter(
                user=request.user, is_active=True
            ).first()
            if ig_account and ig_account.token_expires_at:
                days_left = (ig_account.token_expires_at - timezone.now()).days
                if days_left <= 0:
                    top_banners.insert(0, {
                        'id': 'ig_token_expired',
                        'title': 'Instagram Disconnected',
                        'message': 'Your Instagram connection has expired. Reconnect to keep your automations running.',
                        'banner_type': 'danger',
                        'link_url': '/instagram/connect/',
                        'link_text': 'Reconnect Now',
                        'display_seconds': 0,
                        'is_dismissible': False,
                    })
                elif days_left <= 7:
                    s = '' if days_left == 1 else 's'
                    top_banners.insert(0, {
                        'id': f'ig_token_expiry_{days_left}',
                        'title': 'Instagram Token Expiring',
                        'message': f'Your Instagram connection expires in {days_left} day{s}. Reconnect to avoid disruption.',
                        'banner_type': 'warning',
                        'link_url': '/instagram/connect/',
                        'link_text': 'Reconnect Now',
                        'display_seconds': 0,
                        'is_dismissible': True,
                    })
        except Exception:
            pass

    return {'banners': top_banners, 'popup_banners': popup_banners}
