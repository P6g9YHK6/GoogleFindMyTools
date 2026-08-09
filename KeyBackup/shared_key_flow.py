#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import logging
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from Auth.auth_flow import SIGN_IN_WAIT_S
from Auth.token_cache import set_cached_value
from chrome_driver import create_driver
from KeyBackup.response_parser import get_fmdn_shared_key
from KeyBackup.shared_key_request import get_security_domain_request_url
from KeyBackup.vault_web_api import fetch_vault_keys_via_web_app

logger = logging.getLogger(__name__)


def request_shared_key_flow():
    driver = create_driver()
    try:
        # Open Google accounts sign-in page
        driver.get("https://accounts.google.com/")

        # Wait for user to sign in and redirect to https://myaccount.google.com
        logger.info("Waiting up to %ss for you to sign in...", SIGN_IN_WAIT_S)
        try:
            WebDriverWait(driver, SIGN_IN_WAIT_S).until(
                ec.url_contains("https://myaccount.google.com")
            )
        except TimeoutException:
            # Selenium's own TimeoutException carries no message - give this a
            # clear one instead, same as Auth/auth_flow.py's sign-in wait.
            raise TimeoutError(
                f"Timed out after {SIGN_IN_WAIT_S}s waiting for you to sign in to your "
                f"Google account for the encryption confirmation step. Click \"Sign in "
                f"with Google\" again to retry."
            ) from None
        logger.info("Signed in successfully.")

        # Best-effort: also pull every owner key version via the same internal
        # RPC the real Find My Device web app uses (see KeyBackup/vault_web_api.py).
        # GetEidInfoForE2eeDevices (the endpoint the rest of this codebase uses)
        # always hands back only its own idea of "current", regardless of what
        # version is requested - this is the only way found so far to reach
        # the others. Each entry is itself still encrypted with the account's
        # one stable shared key (confirmed empirically: decrypting one with
        # get_shared_key() reproduces the exact owner key already cached from
        # the normal flow), so cache the raw blobs now and unwrap them lazily
        # wherever get_shared_key() is actually available - see
        # SpotApi/GetEidInfoForE2eeDevices/get_owner_key.py's
        # get_owner_key_from_wrapped_blob(). Any failure here is non-fatal to
        # sign-in; the unlock-page flow below is still the primary path.
        for entry in fetch_vault_keys_via_web_app(driver):
            if entry["domain"] == "finder_hw":
                set_cached_value(f"encrypted_owner_key_v{entry['version']}", entry["key"].hex())

        # Open the security domain request URL
        security_url = get_security_domain_request_url()
        driver.get(security_url)

        # Inject JavaScript interface: the vault page calls these to hand the
        # shared keys back to us (or tell us it gave up), surfaced as an
        # alert() we poll for below since there's no other channel out of the page.
        driver.execute_script("""
        window.mm = {
            setVaultSharedKeys: function(str, vaultKeys) {
                console.log('setVaultSharedKeys called with:', str, vaultKeys);
                alert(JSON.stringify({ method: 'setVaultSharedKeys', str: str, vaultKeys: vaultKeys }));
            },
            closeView: function() {
                console.log('closeView called');
                alert(JSON.stringify({ method: 'closeView' }));
            }
        };
        """)

        logger.info("Waiting up to %ss for the encryption confirmation...", SIGN_IN_WAIT_S)
        deadline = time.monotonic() + SIGN_IN_WAIT_S
        while time.monotonic() < deadline:
            try:
                WebDriverWait(driver, 0.5).until(ec.alert_is_present())
            except TimeoutException:
                continue  # no alert yet - keep polling until the deadline

            alert = driver.switch_to.alert
            message = alert.text
            alert.accept()

            try:
                data = json.loads(message)
            except ValueError:
                logger.warning("Ignoring unparseable alert: %r", message)
                continue

            if data.get("method") == "setVaultSharedKeys":
                logger.info("Received Shared Key.")
                return get_fmdn_shared_key(data["vaultKeys"]).hex()
            elif data.get("method") == "closeView":
                raise RuntimeError(
                    "Google closed the encryption confirmation without providing a key "
                    "(it may have been cancelled, or failed on Google's side). Click "
                    "\"Sign in with Google\" again to retry."
                )

        raise TimeoutError(
            f"Timed out after {SIGN_IN_WAIT_S}s waiting for the encryption confirmation "
            f"step to complete. Click \"Sign in with Google\" again to retry."
        )
    finally:
        driver.quit()


if __name__ == "__main__":
    print(request_shared_key_flow())
