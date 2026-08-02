from Auth.token_cache import get_cached_value


def is_logged_in() -> bool:
    return bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))
