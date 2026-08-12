import asyncio
import base64
import binascii
import logging
import threading

from Auth.firebase_messaging import FcmPushClient, FcmRegisterConfig
from Auth.token_cache import get_cached_value, set_cached_value

logger = logging.getLogger(__name__)


class FcmReceiver:

    _instance = None
    _listening = False
    _loop = None
    _loop_thread = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        # Define Firebase project configuration
        project_id = "google.com:api-project-289722593072"
        app_id = "1:289722593072:android:3cfcf5bc359f0308"
        api_key = "AIzaSyD_gko3P392v6how2H7UpdeXQ0v2HLettc"
        message_sender_id = "289722593072"

        # APK signing certificate SHA1
        android_cert_sha1 = "38918a453d07199354f8b19af05ec6562ced5788"
        bundle_id = "com.google.android.apps.adm"

        fcm_config = FcmRegisterConfig(
            project_id=project_id,
            app_id=app_id,
            api_key=api_key,
            messaging_sender_id=message_sender_id,
            bundle_id=bundle_id,
            android_package=bundle_id,
            android_cert_sha1=android_cert_sha1
        )

        self.credentials = get_cached_value('fcm_credentials')
        self.location_update_callbacks = []
        self._callbacks_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self.pc = FcmPushClient(self._on_notification, fcm_config, self.credentials, self._on_credentials_updated)


    def _ensure_listening(self):
        """Starts the background FCM listener exactly once, even if several
        callers race to be the first one that needs it - e.g. two devices'
        polls landing close together, which is the common case right after
        a restart (every device's schedule is freshly evaluated at once).
        The bare `if not self._listening: self._start_listener_in_background()`
        this replaced let two callers both see False and both start a
        listener concurrently against the same shared self.pc, corrupting
        its internal connection state - observed in production as
        "readexactly() called while another coroutine is already waiting
        for incoming data", crashing the listener and timing out every
        locate that was waiting on it. Returns the account's gcm android_id
        either way, matching what _start_listener_in_background() itself
        returns, so get_android_id() below can use this as its one path
        regardless of whether this call actually started anything."""
        if self._listening:
            return self.credentials['gcm']['android_id']
        with self._start_lock:
            if self._listening:
                return self.credentials['gcm']['android_id']
            return self._start_listener_in_background()


    def register_for_location_updates(self, callback):

        self._ensure_listening()

        with self._callbacks_lock:
            self.location_update_callbacks.append(callback)

        return self.credentials['fcm']['registration']['token']


    def unregister_callback(self, callback):
        with self._callbacks_lock:
            if callback in self.location_update_callbacks:
                self.location_update_callbacks.remove(callback)


    def get_fcm_token(self):
        self._ensure_listening()

        return self.credentials['fcm']['registration']['token']


    def stop_listening(self):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.pc.stop(), self._loop)
        self._listening = False


    def clear(self):
        """Resets this singleton so the next FcmReceiver() call re-registers
        from scratch, e.g. after the web UI's "Clear credentials" button wipes
        fcm_credentials from secrets.json. Without this, __init__ only ever
        reads the cache once (at first instantiation) and this instance would
        keep silently serving its old in-memory self.credentials forever,
        never noticing the file changed underneath it."""
        self.stop_listening()
        FcmReceiver._instance = None


    def get_android_id(self):

        if self.credentials is None:
            return self._ensure_listening()

        return self.credentials['gcm']['android_id']


    # Define a callback function for handling notifications
    def _on_notification(self, obj, notification, data_message):

        # Check if the payload is present
        if 'data' in obj and 'com.google.android.apps.adm.FCM_PAYLOAD' in obj['data']:

            # Decode the base64 string
            base64_string = obj['data']['com.google.android.apps.adm.FCM_PAYLOAD']
            decoded_bytes = base64.b64decode(base64_string)

            # Convert to hex string
            hex_string = binascii.hexlify(decoded_bytes).decode('utf-8')

            with self._callbacks_lock:
                callbacks = list(self.location_update_callbacks)

            for callback in callbacks:
                callback(hex_string)
        else:
            logger.warning("Payload not found in the notification.")


    def _on_credentials_updated(self, creds):
        self.credentials = creds

        # Also store to disk
        set_cached_value('fcm_credentials', self.credentials)
        logger.info("Credentials updated.")


    async def _register_for_fcm(self):
        fcm_token = None

        # Register or check in with FCM and get the FCM token
        while fcm_token is None:
            try:
                fcm_token = await self.pc.checkin_or_register()
            except Exception:
                await self.pc.stop()
                logger.warning("Failed to register with FCM. Retrying...")
                await asyncio.sleep(5)


    async def _register_for_fcm_and_listen(self):
        await self._register_for_fcm()
        # Start the FCM listener
        await self.pc.start()

    def _run_event_loop_in_thread(self):
        """Run the event loop in a background thread"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _start_listener_in_background(self):
        """Start FCM listener in a background thread with its own event loop"""
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_event_loop_in_thread, daemon=True)
        self._loop_thread.start()

        # Register for FCM first (blocking)
        temp_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(temp_loop)
        temp_loop.run_until_complete(self._register_for_fcm())
        temp_loop.close()

        # Now start the listener in the background loop
        asyncio.run_coroutine_threadsafe(self.pc.start(), self._loop)
        self._listening = True
        logger.info("Listening for notifications. This can take a few seconds...")

        return self.credentials['gcm']['android_id']


if __name__ == "__main__":
    receiver = FcmReceiver()
    print(receiver.get_android_id())
