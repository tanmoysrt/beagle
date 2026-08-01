You maintain Beagle's conventions block. Given the full rules table
(id, text, author, date, hit count), produce a single markdown block of at
most {{budget}} tokens for inclusion in every review prompt.

- One imperative line per rule, prefixed with its id, e.g.
  "R12: Use snake_case for HTTP handler names."
- Merge overlapping rules, keeping all merged ids on one line.
- Order by hit count (most-applied first).
- Preserve meaning exactly; never invent, soften, or generalize a rule.
