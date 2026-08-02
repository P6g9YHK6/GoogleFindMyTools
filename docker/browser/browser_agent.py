import threading

from fastapi import FastAPI

from Auth.aas_token_retrieval import get_aas_token
from Auth.token_cache import get_cached_value

app = FastAPI(title="GoogleFindMyTools Browser Agent")

_lock = threading.Lock()
_state = {"in_progress": False, "error": None}


def _run_login():
    with _lock:
        _state["in_progress"] = True
        _state["error"] = None

    try:
        get_aas_token()
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["in_progress"] = False


@app.post("/login/start")
def login_start():
    with _lock:
        already_running = _state["in_progress"]
        if not already_running:
            threading.Thread(target=_run_login, daemon=True).start()

    return {"started": not already_running}


@app.get("/login/status")
def login_status():
    logged_in = bool(get_cached_value("aas_token") and get_cached_value("fcm_credentials"))
    with _lock:
        return {
            "logged_in": logged_in,
            "in_progress": _state["in_progress"],
            "error": _state["error"],
        }
