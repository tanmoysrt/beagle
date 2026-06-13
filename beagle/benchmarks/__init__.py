"""Deterministic benchmark for beagle's extraction, resolution, and retrieval.

The synthetic fixture (``fixture.py``) is small and self-contained, so its
ground truth (``gold.py``) is fully enumerable — every expected symbol, edge,
and resolution is listed. That makes the precision/recall numbers exact rather
than estimated. ``runner.py`` scores an index against the gold and checks it
against the design/05 targets.
"""
