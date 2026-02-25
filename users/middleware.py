from urllib.parse import urlparse

UTM_PARAMS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content')
SESSION_KEY = '_acquisition'


class AcquisitionTrackingMiddleware:
    """Capture UTM parameters and HTTP referrer into the session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        existing = request.session.get(SESSION_KEY)

        # Already have UTM or referrer data — nothing more to capture
        if existing and (existing.get('utm_source') or existing.get('referrer')):
            return self.get_response(request)

        data = existing or {}

        # Capture UTM params from query string
        for param in UTM_PARAMS:
            value = request.GET.get(param, '').strip()
            if value:
                data[param] = value[:200]

        # Capture HTTP referrer (skip own domain)
        if not data.get('referrer'):
            referrer = request.META.get('HTTP_REFERER', '').strip()
            if referrer:
                try:
                    parsed = urlparse(referrer)
                    if parsed.scheme and parsed.netloc:
                        host = request.get_host().split(':')[0]
                        ref_domain = parsed.netloc.split(':')[0]
                        if ref_domain != host:
                            data['referrer'] = referrer[:2000]
                            data['referrer_domain'] = ref_domain[:253]
                except Exception:
                    pass

        # Always keep the first landing page
        if 'landing_page' not in data:
            data['landing_page'] = request.get_full_path()[:2000]

        request.session[SESSION_KEY] = data

        return self.get_response(request)
