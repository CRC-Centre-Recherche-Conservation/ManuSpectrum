"""The IIIF Auth service blocks every protected resource declares (Auth 1.0 and 2.0).

``auth1_block`` is the Auth 1.0 login (cookie) service holding the token and
logout services, in the ``@id``/``@type`` form the Presentation 3 service
registry scopes; its strings are plain, in ``settings.LANGUAGE_CODE`` (Auth
1.0 has no language maps). ``auth2_probe`` is the Auth 2.0 probe service of
one stored file, holding the access service (the same login page, profile
``active``) with its token and logout services; its strings are language
maps. ``v2_auth1_block`` is the Auth 1.0 block as Presentation 2.1 declares
it. Every block is the same for every reader.

``description_401`` is the body of a 401: the requested resource described
with its services, ``type`` ``Dataset`` (both blocks, the probe naming
*file_id*) or any other type (the Auth 1.0 block only).
"""

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext, gettext_noop

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.constants import PRESENTATION_3

AUTH1_CONTEXT = "http://iiif.io/api/auth/1/context.json"
AUTH2_CONTEXT = "http://iiif.io/api/auth/2/context.json"
LOGIN_PROFILE = "http://iiif.io/api/auth/1/login"
TOKEN_PROFILE = "http://iiif.io/api/auth/1/token"
LOGOUT_PROFILE = "http://iiif.io/api/auth/1/logout"

LABEL = gettext_noop("Sign in to ManuSpectrum")
HEADER = gettext_noop("Restricted data")
DESCRIPTION = gettext_noop(
    "Some data of ManuSpectrum are restricted. Sign in with your ManuSpectrum "
    "account to read what it gives access to."
)
NOTE = gettext_noop(
    "Sign in with your ManuSpectrum account to read what it gives access to."
)
CONFIRM = gettext_noop("Sign in")
FAILURE_HEADER = gettext_noop("Not available")
FAILURE_DESCRIPTION = gettext_noop("Your account does not give access to these data.")
LOGOUT_LABEL = gettext_noop("Sign out of external viewers")


def plain(msgid):
    """*msgid* in ``settings.LANGUAGE_CODE``."""
    with translation.override(settings.LANGUAGE_CODE):
        return gettext(msgid)


def auth1_block():
    """The Auth 1.0 login service with its nested token and logout services."""
    return {
        "@id": ids.auth_login(),
        "@type": "AuthCookieService1",
        "profile": LOGIN_PROFILE,
        "label": plain(LABEL),
        "header": plain(HEADER),
        "description": plain(DESCRIPTION),
        "confirmLabel": plain(CONFIRM),
        "failureHeader": plain(FAILURE_HEADER),
        "failureDescription": plain(FAILURE_DESCRIPTION),
        "service": [
            {
                "@id": ids.auth_token(1),
                "@type": "AuthTokenService1",
                "profile": TOKEN_PROFILE,
            },
            {
                "@id": ids.auth_logout(),
                "@type": "AuthLogoutService1",
                "profile": LOGOUT_PROFILE,
                "label": plain(LOGOUT_LABEL),
            },
        ],
    }


def v2_auth1_block():
    """The Auth 1.0 login service as a Presentation 2.1 resource declares it."""
    return {
        "@context": AUTH1_CONTEXT,
        "@id": ids.auth_login(),
        "profile": LOGIN_PROFILE,
        "label": plain(LABEL),
        "header": plain(HEADER),
        "description": plain(DESCRIPTION),
        "confirmLabel": plain(CONFIRM),
        "failureHeader": plain(FAILURE_HEADER),
        "failureDescription": plain(FAILURE_DESCRIPTION),
        "service": [
            {"@id": ids.auth_token(1), "profile": TOKEN_PROFILE},
            {
                "@id": ids.auth_logout(),
                "profile": LOGOUT_PROFILE,
                "label": plain(LOGOUT_LABEL),
            },
        ],
    }


def auth2_probe(file_id):
    """The Auth 2.0 probe service of the stored file *file_id*."""
    return {
        "id": ids.auth_probe(file_id),
        "type": "AuthProbeService2",
        "service": [
            {
                "id": ids.auth_login(),
                "type": "AuthAccessService2",
                "profile": "active",
                "label": lang.gettext_map(LABEL),
                "heading": lang.gettext_map(HEADER),
                "note": lang.gettext_map(NOTE),
                "confirmLabel": lang.gettext_map(CONFIRM),
                "service": [
                    {
                        "id": ids.auth_token(2),
                        "type": "AuthAccessTokenService2",
                        "errorHeading": lang.gettext_map(FAILURE_HEADER),
                        "errorNote": lang.gettext_map(FAILURE_DESCRIPTION),
                    },
                    {
                        "id": ids.auth_logout(),
                        "type": "AuthLogoutService2",
                        "label": lang.gettext_map(LOGOUT_LABEL),
                    },
                ],
            }
        ],
    }


def dataset_services(file_id):
    """The ``service`` of a body served by the data routes: both blocks."""
    return [auth1_block(), auth2_probe(file_id)]


def description_401(url, type_, file_id=None):
    """The 401 body describing *url* as a *type_* with the services a client signs in through."""
    if type_ == "Dataset" and file_id:
        return {
            "@context": [AUTH2_CONTEXT, PRESENTATION_3],
            "id": url,
            "type": type_,
            "service": dataset_services(file_id),
        }
    return {
        "@context": PRESENTATION_3,
        "id": url,
        "type": type_,
        "service": [auth1_block()],
    }
