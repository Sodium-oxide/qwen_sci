# review

Review code for bugs, security issues, and quality.

## When to use

Use when the user asks to review code, a PR, or a diff.

## Workflow

1. Read the changed files or diff thoroughly
2. Check for:
   - **Bugs**: logic errors, off-by-one, null/undefined access, race conditions
   - **Security**: injection, XSS, hardcoded secrets, path traversal
   - **Performance**: N+1 queries, unnecessary allocations, missing indexes
   - **Tests**: are new code paths covered? Are edge cases tested?
   - **Style**: naming consistency, dead code, unnecessary complexity
3. Provide concrete, actionable feedback with file:line references
4. Prioritize findings by severity (critical > major > minor > nit)

For this repository, follow the root `AGENTS.md` lightweight strategy: perform review
as an implementation self-check for ordinary local changes. Start an independent
review only for high-risk architecture/API/security/persistence changes, cross-module
changes with unclear local impact, repeated unresolved fixes, a milestone, or final
delivery. Batch related changes into one review instead of reviewing every subtask.

## Rules

- Be specific: "line 42 may throw if `user` is null" not "check for null"
- Suggest fixes, don't just point out problems
- Acknowledge good patterns too
- Don't nitpick formatting if there's a linter
- Do not make review a subtask-level blocking gate when no material risk is present.
