import pathlib
import time

from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from webui import config, scheduler
from webui.colors import location_color

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
        "build_branch": config.GFMT_BUILD_BRANCH,
        "uptime_str": _format_uptime(time.monotonic() - config.APP_START_TIME),
    }


# One entry per top-level page base.html's nav links to - lets it highlight
# the current page (and pre-open the Settings group when landing directly on
# one of its three pages) purely from the request path, the same
# derive-it-once-in-a-context-processor approach _build_info uses above,
# instead of every one of those six routers' TemplateResponse calls passing
# an identical "which page is this" value along by hand.
_NAV_PAGES = {
    "/": "devices",
    "/firmware": "firmware",
    "/settings": "settings",
    "/staleness": "staleness",
    "/logs": "logs",
    "/auth": "auth",
}


def _active_page(request: Request) -> dict:
    return {"active_page": _NAV_PAGES.get(request.url.path)}


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[_build_info, _active_page])
# Lets the schedule editor's cron preview render inline on the initial page
# load (settings/_endpoint_fields.html calls cron_preview(cron_value)
# directly) without threading a computed value through every route that
# renders that partial - the live htmx update in webui/routers/settings.py
# calls the exact same function, so the two can never disagree.
templates.env.globals["cron_preview"] = scheduler.cron_preview
# Lets devices/_locate_cell.html color each location's swatch the same as
# its map pin (see webui/colors.py) without every caller threading the
# color through by hand.
templates.env.globals["location_color"] = location_color
