import logging
import requests
from functools import lru_cache

logger = logging.getLogger(__name__)

# Default pricing for non-Indian users (fallback)
DEFAULT_INTERNATIONAL_PRICING = {
    'currency': 'USD',
    'symbol': '$'
}


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@lru_cache(maxsize=1000)
def get_country_from_ip(ip_address):
    """
    Get country code from IP address using ip-api.com (free, no API key needed).
    Returns country code (e.g., 'IN', 'US') or None if detection fails.
    Results are cached to reduce API calls.
    """
    if not ip_address or ip_address in ('127.0.0.1', 'localhost', '::1'):
        return 'US'  # Default to US for local development

    try:
        response = requests.get(
            f'http://ip-api.com/json/{ip_address}?fields=status,countryCode',
            timeout=2
        )
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return data.get('countryCode')
    except Exception as e:
        logger.warning(f"IP geolocation failed for {ip_address}: {e}")

    return None


def get_user_country(request):
    """
    Get user's country code from request.
    Checks session cache first, then does IP lookup.

    For local testing, add ?country=US to the URL to override.
    """
    # Allow override via query param for testing (e.g., ?country=US)
    override_country = request.GET.get('country')
    if override_country:
        override_country = override_country.upper()
        request.session['user_country'] = override_country
        return override_country

    # Check if already cached in session
    country_code = request.session.get('user_country')
    if country_code:
        return country_code

    # Get from IP
    ip = get_client_ip(request)
    country_code = get_country_from_ip(ip)

    # Cache in session
    if country_code:
        request.session['user_country'] = country_code

    return country_code or 'US'  # Default to US for international users


def is_indian_user(request):
    """Check if user is from India."""
    return get_user_country(request) == 'IN'


def get_currency_for_user(request):
    """
    Get currency info for user based on their location.
    Returns dict with 'currency' and 'symbol'.
    """
    country = get_user_country(request)
    if country == 'IN':
        return {'currency': 'INR', 'symbol': '₹'}
    return DEFAULT_INTERNATIONAL_PRICING
