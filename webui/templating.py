import pathlib

from fastapi.templating import Jinja2Templates

BASE_DIR = pathlib.Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
