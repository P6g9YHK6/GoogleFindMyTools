# Security Policy

## Reporting a vulnerability

If you find a security issue in this project, please report it privately
instead of opening a public issue or pull request:

- Preferred: open a [GitHub Security Advisory](../../security/advisories/new)
  for this repository (Security tab -> Report a vulnerability). This keeps
  the report private until a fix is ready.
- Alternative: email the maintainer listed on the GitHub profile that owns
  this repository.

Please include:

- What you found and why it's a security issue (not just a bug).
- Steps to reproduce, or a minimal proof of concept.
- The version/commit you tested against.

You should get an acknowledgement within a few days. This is a small
self-hosted project maintained on a best-effort basis, not a funded
security team - please be patient, and thank you for reporting responsibly
instead of disclosing publicly first.

## Scope

This app holds long-lived Google account tokens and live device location
data (see the README's Security section for the deployment model - it's
meant for a trusted LAN, not the open internet). In scope:

- Anything that lets an unauthenticated or unauthorized party read or
  exfiltrate credentials, tokens, or location data.
- Anything that bypasses `HTTP_USER`/`HTTP_PASSWORD` when both are set.
- Anything that lets a party without filesystem/container access decrypt
  `auth.yaml` when `SECRETS_ENCRYPTION_KEY` is set.
- Remote code execution, path traversal, injection, or similar in the web
  UI or its API.

Out of scope: issues that require an attacker who already has shell/
filesystem access to the container or host it runs on - that's already full
compromise regardless of anything this app does.

## Supported versions

Only the latest code on `main` (and the most recently published Docker
image built from it) is supported. There's no separate LTS branch - please
update before reporting if you're on an older build.
