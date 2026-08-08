#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json
import time

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from Auth.auth_flow import SIGN_IN_WAIT_S
from Auth.token_cache import set_cached_value
from Auth.web_session import capture_web_session_cookies
from chrome_driver import create_driver
from KeyBackup.response_parser import get_fmdn_shared_key
from KeyBackup.shared_key_request import get_security_domain_request_url
from KeyBackup.vault_web_api import fetch_vault_keys_via_web_app


def request_shared_key_flow():
    driver = create_driver()
    try:
        # Open Google accounts sign-in page
        driver.get("https://accounts.google.com/")

        # Wait for user to sign in and redirect to https://myaccount.google.com
        print(f"[SharedKeyFlow] Waiting up to {SIGN_IN_WAIT_S}s for you to sign in...")
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
        print("[SharedKeyFlow] Signed in successfully.")

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

        # Same "best-effort, never fail sign-in" spirit as the vault key fetch
        # above - this is what lets Auth/live_device_info.py query Google's
        # real-time push channel later without a browser. driver has just
        # visited www.google.com (for the vault key fetch), so this is the
        # broadest cookie jar this session will have.
        capture_web_session_cookies(driver)

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

        print(f"[SharedKeyFlow] Waiting up to {SIGN_IN_WAIT_S}s for the encryption confirmation...")
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
                print(f"[SharedKeyFlow] Ignoring unparseable alert: {message!r}")
                continue

            if data.get("method") == "setVaultSharedKeys":
                print("[SharedKeyFlow] Received Shared Key.")
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
