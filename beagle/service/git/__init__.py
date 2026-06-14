"""Git repository service (design/15 §6, §7).

Bare mirrors are the canonical object store. Upstream history is fetched into a
``refs/beagle/upstream/*`` namespace; users may only push into their own
``refs/beagle/users/<id>/*`` and ``refs/beagle/workspaces/<id>/*`` namespaces.
"""
