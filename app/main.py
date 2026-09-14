from fastapi import FastAPI

from app.routes import router

app = FastAPI(title="image-editor")
app.include_router(router)
