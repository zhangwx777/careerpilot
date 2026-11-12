from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    """Serve browser routes on refresh while keeping API/asset 404s intact."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            routes = {"dashboard", "applications", "smart-entry", "timeline", "intel",
                      "planner", "practice", "daily-briefings", "settings"}
            if exc.status_code != 404 or scope["method"] not in {"GET", "HEAD"} or path.replace("\\", "/").split("/")[0] not in routes:
                raise
            return await super().get_response("index.html", scope)
