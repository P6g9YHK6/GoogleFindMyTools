"""The Docker image's actual entrypoint (see docker/web/Dockerfile's CMD) -
replaces a bare `uvicorn webui.main:app` CLI invocation so startup can
decide whether to serve HTTPS.

Local dev via `uvicorn webui.main:app --reload` (see CONTRIBUTING.md) is
untouched by any of this - HTTPS only ever applies through this module.
"""

import uvicorn

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
