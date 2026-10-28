from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from minibird.customers import router
from minibird.web import router as web_router

app = FastAPI(title="MiniBird", version="0.0.1")
app.include_router(router)
app.include_router(web_router)


@app.get("/")
def home(request: Request):
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/ui/customers", status_code=303)
    return {"name": "MiniBird", "status": "under development"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/ui", "/login", "/logout")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response
