"""Security headers for every response.

This is a private operations panel: nothing may be indexed by search engines, embedded in other sites,
cached by browsers / proxies, or opened by another origin. See also robots.txt (core/views.py) and the
`ident=""` waitress option in core/management/commands/serve.py (no "Server: waitress" header).
"""
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
       "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'none'")

PERMISSIONS = ("camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), "
               "hid=(), midi=(), magnetometer=(), gyroscope=(), accelerometer=(), display-capture=(), "
               "browsing-topics=()")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        h = response.headers
        h.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        h.setdefault("Permissions-Policy", PERMISSIONS)
        h.setdefault("Content-Security-Policy", CSP)
        h["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet, noimageindex"   # never in search results
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        h["Cache-Control"] = "no-store"     # static files are served earlier by WhiteNoise
        h.pop("Server", None)
        return response
