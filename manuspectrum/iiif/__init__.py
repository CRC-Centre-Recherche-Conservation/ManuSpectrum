"""One IIIF package for the whole project: every IIIF document is built here.

The package never reads a request and never imports a view
(``tests/test_iiif_imports.py``); thin views in ``manuspectrum/views/iiif/``
answer the routes.
"""
