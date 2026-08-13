# Claude Code Bootstrap Prompt

You are implementing a production-minded local-first book discovery application.

The repository root contains:

- `APP_SPECIFICATION.md` — complete product and engineering source of truth;
- `CLAUDE.md` — persistent implementation rules.

## Task

1. Read both files completely.
2. Inspect the current repository and existing code.
3. Do not code immediately.
4. Create `docs/implementation/plan.md` containing:
   - current repository assessment;
   - gaps relative to the specification;
   - phased implementation plan matching the specification;
   - concrete acceptance checklist;
   - risks and assumptions;
   - exact commands that validate each phase.
5. Create or update the ADRs for already approved decisions.
6. Present a concise plan summary.
7. Implement **Phase 0 and Phase 1 only** unless explicitly asked to continue.
8. Run all checks relevant to Phase 1.
9. Report:
   - files created or changed;
   - commands and results;
   - unresolved issues;
   - exact next phase.

## Constraints

- Treat `APP_SPECIFICATION.md` as authoritative.
- Do not replace the architecture with microservices or a generic CRUD app.
- Do not implement the final recommender pipeline.
- Build only the typed boundary plus mock/popularity providers in the relevant later phase.
- Do not use SQLite.
- Do not invent dataset columns or timestamps.
- Do not import the full catalog at API startup.
- Do not skip tests, migrations, security, or error states.
- Do not ask questions already answered in the specification.
- For a genuinely unspecified detail, choose a conservative reversible default and record it.

After Phase 1 is complete, stop and wait.
