---
layout: home

hero:
  name: beagle
  text: Local code-discovery for Python & Frappe
  tagline: >-
    Index a repo into a local SQLite graph, then ask about symbols, callers,
    DocTypes, hooks, jobs, and lifecycle events — every fact carrying
    confidence, evidence, and the exact source range to read. Deterministic,
    no LLM in the engine. Pairs with Claude Code over MCP.
  image:
    src: /logo.svg
    alt: beagle
  actions:
    - theme: brand
      text: Get started
      link: /guide/introduction
    - theme: alt
      text: Quickstart
      link: /guide/quickstart
    - theme: alt
      text: View on GitHub
      link: https://github.com/tanmoysrt/beagle

features:
  - icon: 🐍
    title: Python & Frappe aware
    details: >-
      Understands DocTypes, fields, controllers, hooks.py, background jobs,
      whitelisted endpoints, ORM operations, and document lifecycle events —
      not just generic Python symbols.
  - icon: 🔗
    title: Full-stack tracing
    details: >-
      Resolves JS/TS/Vue call sites (frappe.call, the client ORM, frappe-ui
      resources) to the backend methods and DocTypes they hit. Answers
      "which backend method runs when I click this button?"
  - icon: 🎯
    title: Deterministic, evidence-first
    details: >-
      No model in the loop. Every resolved edge records confidence, resolver,
      evidence, source range, and owner file. Ambiguous facts stay ambiguous
      instead of being guessed into certainty.
  - icon: 🤖
    title: Built for Claude Code
    details: >-
      A read-only MCP server exposes the same engine as the CLI. Claude gets
      stable ids and exact ranges to read, instead of scanning the whole repo.
---
