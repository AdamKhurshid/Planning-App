"""CORS handling for the Expo web/PWA client.

A tiny hand-rolled middleware instead of django-cors-headers to keep the
dependency list short. Allowed origins come from TEMPO_CORS_ORIGINS
(comma-separated). While DEBUG is on, localhost/127.0.0.1 origins are always
allowed so the Expo dev server works out of the box.
"""
from django.conf import settings
from django.http import HttpResponse

LOCAL_DEV_PREFIXES = ("http://localhost:", "http://127.0.0.1:")

CORS_HEADERS = {
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Max-Age": "86400",
}


class CORSMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _allowed(self, origin: str) -> bool:
        if settings.DEBUG and origin.startswith(LOCAL_DEV_PREFIXES):
            return True
        allowed = [o.strip() for o in getattr(settings, "TEMPO_CORS_ORIGINS", "").split(",") if o.strip()]
        return origin in allowed

    def __call__(self, request):
        origin = request.headers.get("Origin", "")
        if request.method == "OPTIONS" and origin:
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if origin and self._allowed(origin):
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            for header, value in CORS_HEADERS.items():
                response[header] = value
        return response
