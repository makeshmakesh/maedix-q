"""
URL watermarking utilities for Instagram automation.
Wraps URLs with Maedix branding page for users without premium feature.
"""
import urllib.parse
from core.subscription_utils import get_user_subscription
from core.models import Configuration


def user_has_direct_links(user):
    """
    Check if user has the 'direct_links' feature (no watermark).
    Returns True if user can use direct links without watermark.
    """
    if not user or not user.is_authenticated:
        return False

    subscription = get_user_subscription(user)
    if not subscription:
        return False

    return subscription.plan.has_feature('direct_links')


def get_watermark_base_url():
    """Get the base URL for watermarked links"""
    app_root_url = Configuration.get_value('app_root_url', 'https://maedix.com')
    return f"{app_root_url.rstrip('/')}/go/"


def wrap_url_with_watermark(url, user=None):
    """
    Wrap a URL with watermark redirect if user doesn't have direct_links feature.

    Args:
        url: The original URL to potentially wrap
        user: The user object (optional, if None always wraps)

    Returns:
        The wrapped URL or original URL based on user's feature access
    """
    if not url or not url.strip():
        return url

    # Clean the URL
    url = url.strip()

    # Don't wrap if user has direct links feature
    if user and user_has_direct_links(user):
        return url

    # Don't re-wrap already wrapped URLs
    watermark_base = get_watermark_base_url()
    if url.startswith(watermark_base):
        return url

    # Also check for /go/ path in case base URL varies
    if '/go/?' in url:
        return url

    # Wrap the URL
    encoded_url = urllib.parse.quote(url, safe='')
    return f"{watermark_base}?url={encoded_url}"


def unwrap_watermarked_url(wrapped_url):
    """
    Extract the original URL from a watermarked URL.

    Args:
        wrapped_url: The wrapped URL

    Returns:
        The original URL or the input if not wrapped
    """
    if not wrapped_url:
        return wrapped_url

    # Check if it's a wrapped URL
    if '/go/?' in wrapped_url and 'url=' in wrapped_url:
        try:
            parsed = urllib.parse.urlparse(wrapped_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if 'url' in query_params:
                return urllib.parse.unquote(query_params['url'][0])
        except:
            pass

    return wrapped_url


def process_flow_node_urls(node_type, config, user):
    """
    Process URLs in a flow node config, wrapping them if needed.

    Args:
        node_type: The type of the node (e.g., 'message_link', 'message_button_template')
        config: The node config dict
        user: The user object

    Returns:
        Modified config dict with processed URLs
    """
    if not config:
        return config

    # Process message_link node
    if node_type == 'message_link':
        if 'url' in config and config['url']:
            config['url'] = wrap_url_with_watermark(config['url'], user)

    # Process message_button_template buttons
    if node_type == 'message_button_template':
        buttons = config.get('buttons', [])
        for btn in buttons:
            if btn.get('type') == 'web_url' and btn.get('url'):
                btn['url'] = wrap_url_with_watermark(btn['url'], user)

    return config


def unwrap_flow_node_urls(node_type, config):
    """
    Unwrap watermarked URLs in a flow node config for display in editor.
    This shows the user their original URL, not the wrapped version.

    Args:
        node_type: The type of the node
        config: The node config dict

    Returns:
        Modified config dict with unwrapped URLs
    """
    if not config:
        return config

    # Make a copy to avoid modifying the original
    import copy
    config = copy.deepcopy(config)

    # Unwrap message_link node URL
    if node_type == 'message_link':
        if 'url' in config and config['url']:
            config['url'] = unwrap_watermarked_url(config['url'])

    # Unwrap message_button_template button URLs
    if node_type == 'message_button_template':
        buttons = config.get('buttons', [])
        for btn in buttons:
            if btn.get('type') == 'web_url' and btn.get('url'):
                btn['url'] = unwrap_watermarked_url(btn['url'])

    return config
