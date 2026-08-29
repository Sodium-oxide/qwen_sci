# test

Write and run tests for code.

## When to use

Use when the user asks to write tests, verify behavior, or improve test coverage.

## Workflow

1. Understand what needs testing:
   - New feature? Write unit tests for the happy path and edge cases
   - Bug fix? Write a regression test that would have caught the bug
   - Refactor? Ensure existing tests still pass
2. Follow the project's testing patterns:
   - Check existing tests for framework (pytest, jest, go test, etc.)
   - Match naming conventions and file organization
   - Use the same fixtures and helpers
3. Write tests that are:
   - Independent: each test can run alone
   - Deterministic: same result every time
   - Fast: mock external services, use in-memory databases
4. Run the tests and verify they pass

For this repository, follow the root `AGENTS.md` lightweight strategy: run the
smallest affected test set during development. Reserve full test suites, complete
builds, full lint, and E2E for milestones or final delivery, and skip a command that
already passed on the same unchanged code unless it covers a newly introduced risk.

## Rules

- Test behavior, not implementation details
- One assertion per test when possible
- Use descriptive test names that explain the scenario
- Don't test framework or library code
- Mock at system boundaries (external APIs, filesystem, network)
- Do not require a full-suite run after every small fix; record why broader checks
  are unnecessary when local validation is sufficient.
