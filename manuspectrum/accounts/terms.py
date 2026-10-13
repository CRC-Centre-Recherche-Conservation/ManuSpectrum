"""Version of the terms of use (`views/pages/terms.htm`).

`TERMS_VERSION` is the date of the text users accept. `TERMS_DIGEST` is the
sha256 of the English template source followed by the French entries of the
catalogue that come from it (`tests/test_about_pages.TermsDigestTests`
recomputes it). When the digest test fails, bump `TERMS_VERSION` if users must
accept the terms again, then update `TERMS_DIGEST`; for a typo fix, update
`TERMS_DIGEST` only.
"""

TERMS_VERSION = "2026-10-12"
TERMS_DIGEST = "f6b9911b06de4d01df27e2dc493a8b0ff19062858f8793b7143704b1148b331f"
