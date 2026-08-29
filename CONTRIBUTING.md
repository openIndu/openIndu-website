# Contributing to openIndu-website

This is the aggregate repository. Application code lives in the submodules
(`openIndu-backend`, `openIndu-admin`, `openIndu-portal`) — make code changes
there, in their own branch + PR, then bump the submodule pointer here via a PR.

For changes to this repo directly (compose, CI, docs):

- Create a focused `feat/…` / `fix/…` / `chore/…` branch; never push to `main`.
- Keep secrets and local `.env` files out of Git.
- Run `docker compose config` to validate compose changes.
- Describe intent, blast radius, test results, and rollback in the PR.

All changes require human review before merge. Every task starts with `/principle`
(see [Governance](README.md#governance)).

## Reporting security issues

Do not open a public issue for a suspected vulnerability. See [SECURITY.md](SECURITY.md).
