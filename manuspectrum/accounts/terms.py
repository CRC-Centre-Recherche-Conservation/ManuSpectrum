"""Version of the terms of use (`views/pages/terms.htm`).

`TERMS_VERSION` is the date of the text users accept. `TERMS_DIGEST` is the
sha256 of the English template source followed by the French entries of the
catalogue that come from it (`tests/test_about_pages.TermsDigestTests`
recomputes it). When the digest test fails, bump `TERMS_VERSION` if users must
accept the terms again, then update `TERMS_DIGEST`; for a typo fix, update
`TERMS_DIGEST` only.
"""

TERMS_VERSION = "2026-10-12"
TERMS_DIGEST = "f28d42ea10efc8da91588e3f7ac79d39ec38e6e3665ef5d99ef7257fad2c92f1"
