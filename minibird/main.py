from fastapi import FastAPI

from minibird.customers import router

app = FastAPI(title="MiniBird", version="0.0.1")
app.include_router(router)


@app.get("/")
def home() -> dict[str, str]:
    return {"name": "MiniBird", "status": "under development"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
