"""
Custom template filters for AI-related templates
"""
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a variable key.

    Usage: {{ mydict|get_item:keyvar }}
    """
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def sum_attr(queryset, attr):
    """
    Sum an attribute across a queryset or list.

    Usage: {{ usage_logs|sum_attr:"total_tokens" }}
    """
    if queryset is None:
        return 0
    total = 0
    for item in queryset:
        value = getattr(item, attr, 0)
        if value is not None:
            total += value
    return total
