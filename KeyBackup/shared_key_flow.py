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
from KeyBackup.response_parser import get_fmdn_shared_key
from KeyBackup.shared_key_request import get_security_domain_request_url
from chrome_driver import create_driver


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
