"""Request id of every request: the caller's ``X-Request-ID`` when it is safe, else a new one."""

from manuspectrum.observability.context import (
    REQUEST_ID_HEADER,
    new_request_id,
    request_id_var,
    safe_request_id,
)


class RequestIdMiddleware:
    """Binds the request id for the request's duration and echoes it in ``X-Request-ID``.

    First in ``MIDDLEWARE`` (after django-prometheus's first middleware when that
    one is installed). The id is reset when the chain returns: gthread serves the
    next request on the same thread. ``request.request_id`` keeps it for what
    logs after the chain (``django.request``'s 4xx/5xx lines).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = (
            safe_request_id(request.headers.get(REQUEST_ID_HEADER)) or new_request_id()
        )
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response[REQUEST_ID_HEADER] = request_id
        return response
