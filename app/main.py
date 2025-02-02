import uvicorn
from fastapi import FastAPI

from api import router as api_router
from config import DEBUG

app = FastAPI(debug=DEBUG)

app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
