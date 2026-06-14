"""Local Beagle MCP bridge (design/15 §1, §7, Phase F).

Runs on the developer's machine: discovers the local repository and Git state,
authenticates with a stored JWT, and talks to the shared service over HTTP and
Git Smart HTTP. It pushes only missing commits, never re-uploading the whole
repository, and supports a local-only mode that uploads nothing.
"""
