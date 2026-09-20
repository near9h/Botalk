# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| `main`  | ✅ active development |
| latest tagged release | ✅ best-effort backports for high/critical issues |

Older tags may receive critical fixes on request; open an issue first.

## Reporting a Vulnerability

**Please do not file a public GitHub issue for security bugs.**

Email: `security@botgroup.local` (placeholder — replace before publishing)

We acknowledge reports within **2 business days** and aim to ship a fix
within **30 days** for high/critical issues.

When reporting, please include:

1. Description of the issue and impact (e.g. "auth bypass", "data leak")
2. Steps to reproduce (curl commands, screenshots, KB document sample if relevant)
3. Affected version / commit SHA
4. Your name / handle (optional, for credit in release notes)

You can optionally encrypt the report with our PGP key — published on
request for confirmed reporters.

## Threat Model (in scope)

- Auth bypass / privilege escalation across `user` and `admin` roles
- KB document leakage across users
- Audit log tampering / missing client IP
- SSRF via document preview / external API URLs
- Path traversal in uploads

## Out of Scope

- Issues that require the attacker to already have `admin` credentials
- Vulnerabilities in upstream dependencies (report upstream instead)
- Self-XSS (paste your own JS in the prompt)
- Rate limiting / DoS at the OpenAI upstream

## Hardening Checklist (for deployers)

See [`.trae/documents/07-testing/security-audit-plan.md`](.trae/documents/07-testing/security-audit-plan.md)
for the full list. Top items:

- [ ] Change `AUTH_BOOTSTRAP_PASSWORD` from default `admin`
- [ ] Set `AUTH_SECRET` (not the auto-generated default)
- [ ] Set `POSTGRES_PASSWORD` to something other than `changeme` / `botgroup`
- [ ] NewAPI key is **not** a personal account key
- [ ] HTTPS in front of Nginx with a real certificate (Let's Encrypt)
- [ ] Restrict PostgreSQL port 5432 to the docker network

## Coordinated Disclosure

We follow a 90-day coordinated disclosure window. After 90 days from
acknowledgement the issue may be publicly disclosed even without a fix.

Thank you for keeping botgroup users safe 🙏