"""The IIIF token and the access cookie behind it (IIIF Auth 1.0 / 2.0).

The login page (``/iiif/auth/login``) gives a signed-in Arches session the
access cookie ``ms_iiif_access`` (``HttpOnly; Secure; SameSite=None;
Path=/iiif/auth/``), signed, holding the user id, a keyed hash of the session
key and a generation nonce. The cache entry ``iiif-auth:session:<hash>``
maps that hash to the session key and the nonce; revoking deletes it.

A IIIF token is ``msiiif1.`` + a ``TimestampSigner`` signature of ``{u, s,
n, o}``: user id, session hash, nonce and the viewer origin it was issued
to. It holds no session key. It verifies while it is younger than
``IIIF_AUTH_TOKEN_TTL``, its origin is trusted (and equals the request's
``Origin`` when one is sent), the cache entry of its session hash exists
with its nonce, that session still exists and belongs to its user, the
account is active and the session's auth hash matches the account's (a
password change ends it). Signing out of Arches, the IIIF logout, the end of
the session or the cookie lifetime end every token of that session.

A token is read-only by construction: it never becomes ``request.user``.
``iiif_reader`` is the reader of the IIIF read routes only: the Arches
session user when the request carries a signed-in session (an OAuth2 bearer
the OAuth2 middleware turned into ``request.user`` is not one), else the user
of a valid Bearer IIIF token, else the visitor. Nothing here logs a token.
"""

import secrets
from importlib import import_module
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.utils.crypto import constant_time_compare, salted_hmac

from manuspectrum.utils.public_visibility import anonymous_user, is_connected

PREFIX = "msiiif1."
TOKEN_SALT = "manuspectrum.iiif-auth.token.v1"
COOKIE_SALT = "manuspectrum.iiif-auth.cookie.v1"
SESSION_SALT = "manuspectrum.iiif-auth.session.v1"
COOKIE_NAME = "ms_iiif_access"
COOKIE_PATH = "/iiif/auth/"
MAX_TOKEN_LENGTH = 1024

NONE, VALID, INVALID = "none", "valid", "invalid"


class TokenError(Exception):
    """A token cannot be issued; ``code`` is the IIIF Auth 1.0 error."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def token_ttl():
    return int(settings.IIIF_AUTH_TOKEN_TTL)


def session_hash(session_key):
    """A keyed hash of *session_key* (32 hex characters)."""
    return salted_hmac(SESSION_SALT, session_key, algorithm="sha256").hexdigest()[:32]


def _entry_key(hashed):
    return f"iiif-auth:session:{hashed}"


def normalized_origin(value):
    """``scheme://host[:port]`` of an http(s) origin, lower case; None for anything else."""
    if not isinstance(value, str) or len(value) > 255:
        return None
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        return None
    origin = f"{parts.scheme}://{parts.hostname}"
    return f"{origin}:{port}" if port is not None else origin


def trusted_origins():
    """The origin of ``PUBLIC_SERVER_ADDRESS`` then ``IIIF_AUTH_TRUSTED_ORIGINS``, normalized, without repeats."""
    found = []
    for value in [settings.PUBLIC_SERVER_ADDRESS, *settings.IIIF_AUTH_TRUSTED_ORIGINS]:
        origin = normalized_origin(value)
        if origin and origin not in found:
            found.append(origin)
    return found


def is_trusted(origin):
    return origin is not None and origin in trusted_origins()


def session_user(request):
    """The account of the request's signed-in Arches session, else None."""
    user = getattr(request, "user", None)
    session = getattr(request, "session", None)
    if session is None or not is_connected(user):
        return None
    return user if str(session.get(SESSION_KEY)) == str(user.pk) else None


def _session_data(session_key):
    engine = import_module(settings.SESSION_ENGINE)
    return engine.SessionStore(session_key).load()


def _live_user(user_id, hashed, nonce):
    """The active account *user_id* when the session behind *hashed* still exists for it with *nonce*."""
    entry = cache.get(_entry_key(hashed))
    if not isinstance(entry, dict):
        return None
    key = entry.get("key")
    if (
        not isinstance(key, str)
        or not constant_time_compare(session_hash(key), hashed)
        or not constant_time_compare(str(entry.get("n", "")), str(nonce))
    ):
        return None
    data = _session_data(key)
    if str(data.get(SESSION_KEY)) != str(user_id):
        return None
    user = User.objects.filter(pk=user_id, is_active=True).first()
    stored = data.get(HASH_SESSION_KEY)
    if (
        user is None
        or not is_connected(user)
        or not isinstance(stored, str)
        or not constant_time_compare(stored, user.get_session_auth_hash())
    ):
        return None
    return user


def set_access_cookie(response, request, user):
    """Give the session of *request* (signed in as *user*) the access cookie; the session's entry keeps its nonce."""
    key = request.session.session_key
    hashed = session_hash(key)
    entry = cache.get(_entry_key(hashed))
    nonce = (
        entry["n"]
        if isinstance(entry, dict) and entry.get("key") == key and entry.get("n")
        else secrets.token_hex(16)
    )
    age = max(
        1,
        min(int(request.session.get_expiry_age()), int(settings.IIIF_AUTH_COOKIE_TTL)),
    )
    cache.set(_entry_key(hashed), {"key": key, "n": nonce}, age)
    response.set_cookie(
        COOKIE_NAME,
        signing.dumps({"u": user.pk, "s": hashed, "n": nonce}, salt=COOKIE_SALT),
        max_age=age,
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="None",
    )


def clear_access_cookie(response):
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, samesite="None")
    response.cookies[COOKIE_NAME]["secure"] = True
    response.cookies[COOKIE_NAME]["httponly"] = True


def _cookie(request):
    """``(user id, session hash, nonce)`` of a valid access cookie, else None."""
    value = request.COOKIES.get(COOKIE_NAME)
    if not value or len(value) > MAX_TOKEN_LENGTH:
        return None
    try:
        data = signing.loads(
            value, salt=COOKIE_SALT, max_age=int(settings.IIIF_AUTH_COOKIE_TTL)
        )
    except (signing.BadSignature, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    user_id, hashed, nonce = data.get("u"), data.get("s"), data.get("n")
    if not isinstance(user_id, int) or not isinstance(hashed, str) or not nonce:
        return None
    return user_id, hashed, nonce


def revoke(session_key):
    """End every IIIF token and access cookie of the session *session_key*."""
    if session_key:
        cache.delete(_entry_key(session_hash(session_key)))


def revoke_cookie(request):
    """End every IIIF token of the session named by the request's access cookie."""
    found = _cookie(request)
    if found:
        cache.delete(_entry_key(found[1]))


def issue(request, origin):
    """``(token, lifetime)`` for the viewer *origin*, from the request's access cookie; ``TokenError`` otherwise."""
    if not is_trusted(origin):
        raise TokenError("invalidOrigin")
    found = _cookie(request)
    user = _live_user(*found) if found else None
    if user is None:
        raise TokenError("missingCredentials")
    _, hashed, nonce = found
    payload = {"u": user.pk, "s": hashed, "n": nonce, "o": origin}
    token = PREFIX + signing.TimestampSigner(salt=TOKEN_SALT).sign_object(payload)
    return token, token_ttl()


def verify(token, origin_header):
    """The account a IIIF *token* reads as, else None; *origin_header* is the request's ``Origin`` (None when absent)."""
    if (
        not isinstance(token, str)
        or not token.startswith(PREFIX)
        or len(token) > MAX_TOKEN_LENGTH
    ):
        return None
    try:
        payload = signing.TimestampSigner(salt=TOKEN_SALT).unsign_object(
            token[len(PREFIX) :], max_age=token_ttl()
        )
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    user_id, hashed, nonce, origin = (payload.get(k) for k in ("u", "s", "n", "o"))
    if (
        not isinstance(user_id, int)
        or not isinstance(hashed, str)
        or not isinstance(origin, str)
        or not is_trusted(origin)
    ):
        return None
    if origin_header is not None and not constant_time_compare(
        normalized_origin(origin_header) or "", origin
    ):
        return None
    return _live_user(user_id, hashed, nonce)


def _bearer(request):
    """The Bearer credential of the request: None without one, else its value (possibly empty)."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip()


def _resolve(request):
    cached = getattr(request, "_iiif_reader", None)
    if cached is not None:
        return cached
    credential = _bearer(request)
    token_user = None
    state = NONE
    if credential is not None:
        token_user = verify(credential, request.META.get("HTTP_ORIGIN"))
        state = VALID if token_user is not None else INVALID
    user = session_user(request)
    by_token = False
    if user is None and token_user is not None:
        user, by_token = token_user, True
    resolved = (user or anonymous_user(), by_token, state)
    request._iiif_reader = resolved
    return resolved


def iiif_reader(request):
    """The reader of a IIIF read route: session user, else the valid Bearer token's user, else the visitor."""
    return _resolve(request)[0]


def by_token(request):
    """Whether the IIIF reader of *request* comes from its Bearer token."""
    return _resolve(request)[1]


def bearer_state(request):
    """``"none"`` without a Bearer credential, ``"valid"`` for a valid IIIF token, ``"invalid"`` otherwise."""
    return _resolve(request)[2]
