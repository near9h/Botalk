---
name: Bug report
about: Report something that doesn't work as expected
title: '[BUG] '
labels: bug
assignees: ''
---

## Describe the bug

A clear and concise description of what the bug is.

## To Reproduce

Steps to reproduce the behaviour:

1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

## Expected behaviour

What you expected to happen instead.

## Environment

- botgroup version / commit: `git describe --tags` (e.g. `v0.1.0-3-gabcd123`)
- Deployment: docker compose / bare metal / dev
- Browser (if UI bug): Chrome 120 / Safari 17 / ...
- Model used (if LLM-related): gpt-4o / claude-3.5 / ...

## Logs / Screenshots

Paste relevant logs (docker compose logs backend | tail -100) or attach
screenshots. **Redact any secrets / API keys / IPs before posting.**

## Additional context

Anything else that might help — KB doc type, group config, etc.

## Severity

How bad is it? (P0 = service down / P1 = core feature broken / P2 = minor)