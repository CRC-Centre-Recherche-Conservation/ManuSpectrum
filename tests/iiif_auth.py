"""Test helpers of the IIIF Auth routes: sign a client in and mint a IIIF token the way a viewer does."""

from django.conf import settings
from django.test import Client

DEMO = "https://crc-centre-recherche-conservation.github.io"


def own_origin():
    return settings.PUBLIC_SERVER_ADDRESS.rstrip("/")


def signed_in(user):
    """A client signed in as *user* that went through ``/iiif/auth/login`` (it holds the access cookie)."""
    client = Client()
    client.force_login(user)
    client.get("/iiif/auth/login")
    return client


def token_for(user, origin=DEMO, client=None):
    """A IIIF token of *user* for *origin*, asked from the token service's JSON form."""
    client = client or signed_in(user)
    message = client.get("/iiif/auth/1/token", {"origin": origin}).json()
    return message["accessToken"]


def bearer(token, origin=DEMO):
    """Request headers of a viewer at *origin* sending *token*."""
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    if origin:
        headers["HTTP_ORIGIN"] = origin
    return headers


def cookie_of(client):
    from manuspectrum.iiif import tokens

    morsel = client.cookies.get(tokens.COOKIE_NAME)
    return morsel.value if morsel else None
