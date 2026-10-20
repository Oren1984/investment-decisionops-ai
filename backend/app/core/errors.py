"""Consistent, actionable API errors: {code, message, help_slug}."""

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400

    def __init__(self, code: str, message: str, *, status_code: int | None = None, help_slug: str | None = None,
                 details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.help_slug = help_slug
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code


class NotFound(AppError):
    def __init__(self, what: str = "Item"):
        super().__init__("not_found", f"{what} not found.", status_code=404)


class Forbidden(AppError):
    def __init__(self, message: str = "You do not have permission to do this.", code: str = "forbidden"):
        super().__init__(code, message, status_code=403)


class Conflict(AppError):
    def __init__(self, code: str, message: str, help_slug: str | None = None, details: dict | None = None):
        super().__init__(code, message, status_code=409, help_slug=help_slug, details=details)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body: dict = {"code": exc.code, "message": exc.message}
    if exc.help_slug:
        body["help_slug"] = exc.help_slug
    if exc.details:
        body["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)
