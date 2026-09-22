from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
import uvicorn

app = FastAPI()

pages = Jinja2Templates(directory="pages")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return pages.TemplateResponse(name="index.html", request=request)


@app.get("/api/status", response_class=JSONResponse)
def status(request: Request):
    return {
  "minutesUsed": 23,
  "dailyLimit": 60,
  "sites": [
    {"name": "YouTube", "domain": "youtube.com", "blocked": False}
  ]
}

if __name__ == '__main__':
    uvicorn.run("server:app", host="localhost", port=4000)
