"""Clients for the third-party data sources the analysis relies on.

Each module here owns exactly one upstream service and is responsible for its
own timeout, caching and failure behaviour. When a service is unavailable the
client returns ``None`` rather than inventing a value -- the API then reports
the gap honestly instead of showing the user a fabricated number.
"""
