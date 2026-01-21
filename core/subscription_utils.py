"""
Subscription utility functions for checking and managing user subscriptions.
"""

from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .models import Subscription, Plan


def get_user_subscription(user, auto_reset=True):
    """Get user's active subscription or None. Auto-resets usage if past reset date."""
    if not user.is_authenticated:
        return None
    subscription = (
        Subscription.objects.filter(user=user, status="active")
        .select_related("plan")
        .first()
    )

    # Auto-reset usage if past reset date
    if subscription and auto_reset:
        check_and_reset_usage(subscription)

    return subscription


def check_and_reset_usage(subscription):
    """Check if subscription usage needs to be reset and reset if needed."""
    if not subscription.next_reset_date:
        return False

    now = timezone.now()
    if now >= subscription.next_reset_date:
        subscription.usage_data = {}
        subscription.last_reset_date = now
        # Set next reset date to first of next month
        next_month = now.replace(day=1) + timezone.timedelta(days=32)
        subscription.next_reset_date = next_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        subscription.save()
        return True
    return False


def get_or_create_free_subscription(user):
    """Get existing subscription or create free plan subscription"""
    subscription = get_user_subscription(user)
    if subscription:
        return subscription

    # Get or create free plan
    free_plan = Plan.objects.filter(plan_type="free", is_active=True).first()
    if not free_plan:
        # Create a default free plan if none exists (IG automation focused)
        free_plan = Plan.objects.create(
            name="Free",
            slug="free",
            plan_type="free",
            price_monthly=0,
            price_yearly=0,
            description="Get started with Instagram automation",
            features=[
                {
                    "code": "ig_post_automation",
                    "limit": 3,
                    "description": "Post-level automations",
                },
                {"code": "ig_comment_reply", "description": "Auto comment replies"},
                {"code": "ig_auto_dm", "description": "Auto follow-up DMs"},
                {"code": "ig_keyword_triggers", "description": "Keyword triggers"},
                {"code": "ig_message_variations", "description": "Multiple message variations (1-5)"},
            ],
            is_active=True,
            order=0,
        )

    # Create subscription for user
    now = timezone.now()
    subscription = Subscription.objects.create(
        user=user,
        plan=free_plan,
        status="active",
        start_date=now,
        end_date=None,  # Free plan doesn't expire
        is_yearly=False,
        usage_data={},
        last_reset_date=now,
        next_reset_date=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        + timezone.timedelta(days=32),
    )
    # Set next_reset_date to first of next month
    next_month = now.replace(day=1) + timezone.timedelta(days=32)
    subscription.next_reset_date = next_month.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    subscription.save()

    return subscription


def check_subscription_active(user):
    """Check if user has an active subscription"""
    # Staff users bypass subscription checks
    if user.is_staff:
        return True, None

    subscription = get_user_subscription(user)
    if not subscription:
        return False, "No active subscription found."

    if not subscription.is_active():
        return False, "Your subscription has expired. Please renew to continue."

    return True, subscription


def check_feature_access(user, feature_code):
    """
    Check if user can access a specific feature.
    Returns (can_access, message, subscription)
    """
    # Staff users bypass subscription checks
    if user.is_staff:
        return True, "Staff access granted", None

    subscription = get_user_subscription(user)

    if not subscription:
        return (
            False,
            "No active subscription. Please subscribe to access this feature.",
            None,
        )

    if not subscription.is_active():
        return (
            False,
            "Your subscription has expired. Please renew to continue.",
            subscription,
        )

    if not subscription.plan.has_feature(feature_code):
        return (
            False,
            f"Your plan doesn't include this feature. Please upgrade.",
            subscription,
        )

    if not subscription.can_use_feature(feature_code):
        remaining = subscription.get_remaining(feature_code)
        feature = subscription.plan.get_feature(feature_code)
        return (
            False,
            f"You've reached your {feature.get('description', 'feature')} limit. Please upgrade for more.",
            subscription,
        )

    return True, "Access granted", subscription


def use_feature(user, feature_code):
    """
    Use a feature and increment usage counter.
    Returns (success, message, subscription)
    """
    # Staff users bypass - no usage tracking
    if user.is_staff:
        return True, "Staff access granted", None

    can_access, message, subscription = check_feature_access(user, feature_code)

    if not can_access:
        return False, message, subscription

    subscription.increment_usage(feature_code)
    return True, "Feature used successfully", subscription


def reset_monthly_usage():
    """
    Reset usage for subscriptions that have passed their reset date.
    Should be called by a cron job or celery task.
    """
    now = timezone.now()
    subscriptions = Subscription.objects.filter(
        status="active", next_reset_date__lte=now
    )

    for subscription in subscriptions:
        subscription.usage_data = {}
        subscription.last_reset_date = now
        # Set next reset date to first of next month
        next_month = now.replace(day=1) + timezone.timedelta(days=32)
        subscription.next_reset_date = next_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        subscription.save()

    return subscriptions.count()


# Decorator for views that require subscription
def subscription_required(feature_code=None, redirect_url="subscription"):
    """
    Decorator to check subscription before allowing access to a view.
    If feature_code is provided, checks if user can use that specific feature.
    Staff users bypass all subscription checks.
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, "Please login to access this feature.")
                return redirect("login")

            # Staff users bypass subscription checks
            if request.user.is_staff:
                return view_func(request, *args, **kwargs)

            if feature_code:
                can_access, message, subscription = check_feature_access(
                    request.user, feature_code
                )
            else:
                can_access, message = check_subscription_active(request.user)

            if not can_access:
                messages.warning(request, message)
                return redirect(redirect_url)

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
