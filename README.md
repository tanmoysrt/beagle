# beagle

Local code-discovery engine for Python and Frappe projects. No LLM required.

`beagle` sniffs out symbols, callers, callees, hooks, jobs, DocTypes, and the
exact source ranges Claude Code should read before changing anything.

See `design/` for architecture and `CLAUDE.md` for development rules.

## Usage

```bash
uv sync
uv run beagle index .
uv run beagle status
uv run beagle search "site deployment"
uv run beagle read <entity-id>
uv run pytest
```
