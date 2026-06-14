"""Shared Beagle service (design/15).

A revision-aware, multi-tenant code-intelligence service. This package is
independent of the local SQLite engine under ``beagle/`` core modules: it owns
organizations, users, JWT identity, Git repository mirrors, and the HTTP API.

Phases implemented here: A (JWT identity) and B (Git repository service).
"""
