"""Shared authorization constants for ManuSpectrum's internal editor APIs."""

# Groups whose members may use the internal editor APIs (the Biblissima
# connector under api/biblissima/*, and the renderer-config write path).
#
# SECURITY INVARIANT — read before editing:
#
# * NEVER add "Resource Exporter" or "Guest" to this tuple. Arches'
#   SetAnonymousUser middleware maps every unauthenticated visitor to the
#   real DB user `anonymous` (whose is_authenticated is True), and that user
#   belongs to BOTH of those groups — including either one would open every
#   gated endpoint to anonymous traffic.
# * NEVER replace the group checks that use this constant with
#   login_required / is_authenticated: `anonymous` IS authenticated. Under
#   Arches, only a group check is a real barrier.
#
# tests/test_biblissima_auth.py locks both properties.
EDITOR_GROUPS = (
    "Resource Editor",
    "Resource Reviewer",
    "RDM Administrator",
    "Application Administrator",
    "System Administrator",
    "Graph Editor",
)
