# 01 — Product Overview

## Goal

Build a local code-discovery tool for Python and Frappe repositories.

It should help Claude Code answer:

- How does a feature work?
- Where is a symbol defined?
- Who calls it?
- What does it call?
- Which hooks, jobs, DocTypes, fields, and tests are related?
- What source should be inspected before changing it?

The tool must work without an LLM.

## Interfaces

```bash
project-index index .
project-index search "site deployment retry"
project-index resolve "Site.deploy"
project-index show "press.press.doctype.site.site.Site.deploy"
project-index relations "Site.deploy"
project-index path "deploy_site" "AgentRequest.execute"
project-index impact "Site.deploy"
project-index context   --intent understand   --query "How does Site deployment work?"   --max-tokens 6000
```

Consumers:

1. CLI
2. Claude Code through MCP

Claude is the only LLM layer; Beagle ships no bundled local model and the
engine itself stays fully deterministic.

## First useful release

Claude Code should be able to ask:

```text
How does Site deployment work?
```

and retrieve:

- likely entrypoints;
- controller methods;
- callers and callees;
- hooks;
- jobs;
- DocType and field relationships;
- related tests;
- exact source ranges;
- confidence and evidence.

Claude should not need to scan large unrelated parts of the repository.
