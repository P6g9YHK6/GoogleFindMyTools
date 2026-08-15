from Auth import token_cache
from Auth.token_cache import get_cached_value


def is_logged_in() -> bool:
    return bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))


def auth_store_ok() -> bool:
    """Whether auth.yaml's most recent read actually succeeded - see
    Auth.token_cache.last_load_ok(). is_logged_in() alone can't tell a
    corrupt store apart from a legitimately logged-out one."""
    return token_cache.last_load_ok()
