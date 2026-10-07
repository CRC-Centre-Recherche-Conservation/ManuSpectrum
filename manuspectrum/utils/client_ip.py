"""Client address of a request that reached Django through nginx.

nginx overwrites `X-Real-IP` with `$remote_addr` on every proxied request and
nothing but nginx reaches `web:8000`, so a valid `X-Real-IP` is the address of
the visitor. Without it every visitor shares the address of the proxy.

A missing or malformed header falls back to `REMOTE_ADDR`, which serves requests
made directly on the internal network (smoke checks, health probes).

Every per-client key or lockout (django-ratelimit through
`RATELIMIT_IP_META_KEY`, django-axes through `AXES_CLIENT_IP_CALLABLE`) must
use this function and never read `REMOTE_ADDR` or `X-Forwarded-For`.
"""

import ipaddress


def client_ip(request):
    value = request.META.get("HTTP_X_REAL_IP", "")
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return request.META.get("REMOTE_ADDR", "")
