# Contributing to ShipAgent

Thank you for your interest in contributing to ShipAgent.

## License Agreement

By submitting a contribution to this repository, you agree that your
contribution will be licensed under the **Apache License, Version 2.0**,
the same license that covers this project. See the [LICENSE](LICENSE) file
for the full terms.

You certify that:

1. The contribution was created in whole or in part by you, and you have
   the right to submit it under the Apache License 2.0; or
2. The contribution is based on previous work that, to the best of your
   knowledge, is covered under an appropriate open source license and you
   have the right to submit that work with modifications under Apache 2.0;
   or
3. The contribution was provided directly to you by some other person who
   certified (1) or (2) above, and you have not modified it.

This is the [Developer Certificate of Origin (DCO)](https://developercertificate.org/).
Please sign off your commits to certify your agreement:

```
git commit -s -m "Your commit message"
```

This adds a `Signed-off-by: Your Name <email@example.com>` trailer to
your commit. Unsigned commits may not be accepted.

## How to Contribute

1. Fork the repository
2. Create a feature branch from `main`:
   ```
   git checkout -b feature/your-feature-name
   ```
3. Make your changes, following the conventions in [CLAUDE.md](CLAUDE.md)
4. Ensure all tests pass:
   ```
   pytest -k "not stream and not sse and not progress"
   ```
5. Format and lint your code:
   ```
   ruff format src/ tests/
   ruff check src/ tests/
   ```
6. Sign off your commit(s):
   ```
   git commit -s -m "feat: describe your change"
   ```
7. Open a Pull Request against the `main` branch

## File Headers

New source files should include the following SPDX header:

```python
# Copyright 2026 Matthew Hans
# SPDX-License-Identifier: Apache-2.0
```

This enables automated license scanning tools to correctly identify the
license of individual files.

## Code Standards

- Follow the architecture principles in [CLAUDE.md](CLAUDE.md) — the
  `OrchestrationAgent` is the sole orchestrator; no business logic in routes
- All new capabilities must be exposed as agent tools, not bypassing the
  agent loop
- External systems must be accessed through MCP servers, not direct imports
- New constants and enums belong in canonical modules in `src/services/`
- Tests required for all new logic (see [CLAUDE.md](CLAUDE.md) for test commands)

## Questions

Open an issue or start a discussion before submitting large changes so we
can align on approach before you invest significant effort.
