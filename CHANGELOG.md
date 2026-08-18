# Changelog

Notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added
- `{{is_semantic}}` and `{{semantic_name}}` are now available as forwarding
  template variables, alongside `status`/`status_id` - a semantic reading's
  named place (e.g. "Nest Mini - Living Room") can now be forwarded
  directly, and templates can branch on a plain boolean instead of
  string-matching `status`.
- The "filter by report type" gate on an endpoint's settings now includes a
  "Named location" checkbox, so semantic readings can be selectively
  allowed or blocked through a given endpoint the same way GPS/WiFi/
  Cellular/Coarse fixes already can. Existing endpoints keep forwarding
  semantic readings as before until this box is actively unchecked.
