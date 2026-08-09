"""The Docker image's actual entrypoint (see docker/web/Dockerfile's CMD) -
replaces a bare `uvicorn webui.main:app` CLI invocation so startup can
decide whether to serve HTTPS.

Local dev via `uvicorn webui.main:app --reload` (see CONTRIBUTING.md) is
untouched by any of this - HTTPS only ever applies through this module.
"""

import uvicorn

# webui.main (not just uvicorn.run's "webui.main:app" import-string below)
# is imported explicitly here so its logging.basicConfig() has already run
# before _uvicorn_kwargs() below gets a chance to log anything (it can, via
# tls.ensure_cert() logging the generated cert's fingerprint). Without this,
# that log call runs before any handler is configured on the root logger,
# and an INFO message with no handler configured is silently dropped
# entirely - not just unformatted, genuinely never shown - unlike a
# WARNING/ERROR, which at least reaches Python's own last-resort handler.
import webui.main  # noqa: F401
from webui import config, tls


def _uvicorn_kwargs() -> dict:
    """Pure/no-I/O except the one deliberate exception: generating or
    loading the TLS cert when HTTPS_ENABLED, since that has to succeed
    before uvicorn can bind. Kept separate from the uvicorn.run() call
    below so this branch is unit-testable without starting a server."""
    kwargs = {"host": "0.0.0.0", "port": 4321}
    if config.HTTPS_ENABLED:
        cert_path, key_path = tls.ensure_cert()
        kwargs["ssl_certfile"] = cert_path
        kwargs["ssl_keyfile"] = key_path
    return kwargs


if __name__ == "__main__":
    # Import-string form (not the imported `app` object) so this behaves
    # identically to the plain-HTTP CLI invocation it replaces.
    uvicorn.run("webui.main:app", **_uvicorn_kwargs())
