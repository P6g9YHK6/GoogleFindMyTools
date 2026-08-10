import pathlib
import time

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from webui import config

BASE_DIR = pathlib.Path(__file__).parent


def _format_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return "< 1m"


def _build_info(request: Request) -> dict:
    """Runs on every template render (see the Jinja2Templates call below) so
    the footer in base.html doesn't need every router's TemplateResponse call
    to pass this along individually."""
    return {
        "build_sha": config.GFMT_BUILD_SHA,
        "build_sha_short": config.GFMT_BUILD_SHA if config.GFMT_BUILD_SHA == "dev" else config.GFMT_BUILD_SHA[:7],
        "build_date": config.GFMT_BUILD_DATE,
        "uptime_str": _format_uptime(time.monotonic() - config.APP_START_TIME),
    }


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[_build_info])
