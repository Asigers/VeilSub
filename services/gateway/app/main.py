from fastapi import FastAPI

from app.live import router as live_router

app = FastAPI(title="VeilSub Gateway", version="0.1.0")
app.include_router(live_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
