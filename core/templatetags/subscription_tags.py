import json
from django import template
from django.utils.safestring import mark_safe
from core.subscription_utils import get_user_subscription

register = template.Library()


@register.filter
def jsonify(value):
    """
    Convert a Python object to JSON for use in JavaScript.
    Usage: {{ my_list|jsonify }}
    """
    return mark_safe(json.dumps(value))


@register.simple_tag
def has_feature(user, feature_code):
    """
    Check if user has access to a specific feature.
    Usage: {% has_feature user 'ig_automation' as can_access %}
    """
    if not user or not user.is_authenticated:
        return False

    # Staff users have access to all features
    if user.is_staff:
        return True

    subscription = get_user_subscription(user, auto_reset=False)
    if not subscription:
        return False

    if not subscription.is_active():
        return False

    return subscription.plan.has_feature(feature_code)


@register.filter
def user_has_feature(user, feature_code):
    """
    Filter to check if user has access to a specific feature.
    Usage: {% if user|user_has_feature:'ig_automation' %}
    """
    return has_feature(user, feature_code)
