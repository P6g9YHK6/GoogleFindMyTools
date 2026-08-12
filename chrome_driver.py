#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#
import logging
import os
import platform
import shutil
import time

import undetected_chromedriver as uc

logger = logging.getLogger(__name__)

_VERSION_MISMATCH_SIGNATURES = ("only supports Chrome version", "session not created")


def _version_mismatch_hint(e: Exception) -> str:
    """undetected_chromedriver (version_main=None below) auto-fetches
    whatever chromedriver build is newest, which can be ahead of a host's
    actual installed Chrome - Chrome's staged rollout vs. chromedriver's
    own release cadence. Selenium surfaces that as a "session not created:
    This version of ChromeDriver only supports Chrome version N" error,
    which otherwise reads like any other opaque failure in this chain.
    Detected here so it points at the two actual ways out instead of
    leaving the raw Selenium message to speak for itself."""
    if any(sig in str(e) for sig in _VERSION_MISMATCH_SIGNATURES):
        return (" This looks like a Chrome/chromedriver version mismatch - set "
                "GFMT_CHROME_BINARY to a specific Chrome executable, or use the "
                "Docker app instead (it downloads a matched Chrome build automatically).")
    return ""


def find_chrome():
    """Find Chrome executable using known paths and system commands."""
    env_path = os.environ.get("GFMT_CHROME_BINARY")
    if env_path and os.path.exists(env_path):
        return env_path

    possiblePaths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\ProgramData\chocolatey\bin\chrome.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/local/bin/google-chrome",
        "/opt/google/chrome/chrome",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ]
    # Check predefined paths
    for path in possiblePaths:
        if os.path.exists(path):
            return path
    # Use system command to find Chrome
    try:
        if platform.system() == "Windows":
            chrome_path = shutil.which("chrome")
        else:
            chrome_path = shutil.which("google-chrome") or shutil.which("chromium")
        if chrome_path:
            return chrome_path
    except Exception as e:
        logger.warning("Error while searching system paths: %s", e)
    return None

def get_options():
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    return chrome_options

def create_driver():
    """Create a Chrome WebDriver with undetected_chromedriver."""
    try:
        # Kill any existing Chrome processes first
        try:
            if platform.system() == "Windows":
                os.system("taskkill /f /im chrome.exe >nul 2>&1")
            else:
                os.system("pkill -f chrome")
            time.sleep(2)  # Wait for processes to close
        except Exception:
            pass
            
        chrome_options = get_options()
        driver = uc.Chrome(options=chrome_options, version_main=None)
        logger.info("Installed and browser started.")
        return driver
    except Exception as e:
        logger.warning("Default ChromeDriver creation failed: %s%s", e, _version_mismatch_hint(e))
        logger.info("Trying alternative paths...")
        chrome_path = find_chrome()
        if chrome_path:
            chrome_options = get_options()
            chrome_options.binary_location = chrome_path
            try:
                driver = uc.Chrome(options=chrome_options, version_main=None)
                logger.info("ChromeDriver started using %s", chrome_path)
                return driver
            except Exception as e:
                logger.warning("ChromeDriver failed using path %s: %s%s", chrome_path, e, _version_mismatch_hint(e))
        else:
            logger.warning("No Chrome executable found in known paths.")

        # Final fallback - try headless mode
        logger.info("Trying headless mode as last resort...")
        try:
            chrome_options = get_options()
            chrome_options.add_argument("--headless")
            driver = uc.Chrome(options=chrome_options, version_main=None)
            logger.info("Started in headless mode successfully.")
            return driver
        except Exception as e:
            logger.error("Headless mode also failed: %s%s", e, _version_mismatch_hint(e))

        raise Exception(
            "[ChromeDriver] Failed to install ChromeDriver. A current version of Chrome was not detected on your system.\n"
            "If you know that Chrome is installed, update Chrome to the latest version. If the script is still not working, "
            "set the path to your Chrome executable manually inside the script, or set GFMT_CHROME_BINARY to point at it "
            "directly, or use the Docker app instead (it downloads a matched Chrome build automatically)."
        )

if __name__ == '__main__':
    create_driver()