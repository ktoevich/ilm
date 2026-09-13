"""Image analysis pipelines.

Each module implements one analysis and returns a plain dict ready to be
serialised. Shared conventions:

* every pipeline takes an already-validated ``bbox`` tuple;
* failures raise :class:`~api.analysis.imagery.AnalysisError` with a message
  that is safe to show the user -- pipelines never return ``None`` silently;
* every result declares how it was produced (``method``) and describes the
  imagery it used (``imagery``: source, acquisition date, ground resolution).
"""
