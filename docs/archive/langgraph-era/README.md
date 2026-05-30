# LangGraph-Era Archive

This directory is for tracked historical documents from the LangGraph implementation period.

Do not put these files in `.gitignore`: architecture history is part of the project record. Active runtime migration decisions live in:

- `docs/adr/002-helloagents-runtime-migration.md`
- `docs/adr/003-nasclawbot-domain-decisions.md`
- `docs/design/helloagents-runtime-architecture.md`

When the original LangGraph-era design and plan files are available in the working tree, archive them here with `git mv`:

```text
docs/design/agent-architecture.md -> docs/archive/langgraph-era/agent-architecture.md
docs/plan/v1-implementation.md    -> docs/archive/langgraph-era/v1-implementation.md
```
