import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .model import QueryRequest

app = FastAPI()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan():
    await config.lifespan(app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logger_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        path=request.url.path,
        method=request.method,
        client_host=request.client.host,
        request_id=str(uuid.uuid4()),
    )
    response = await call_next(request)

    structlog.contextvars.bind_contextvars(
        status_code=response.status_code,
    )

    # Exclude /healthcheck endpoint from producing logs
    if request.url.path != "/healthcheck":
        if 400 <= response.status_code < 500:
            logger.warn("Client error")
        elif response.status_code >= 500:
            logger.error("Server error")
        else:
            logger.info("OK")

    return response


@app.get("/healthcheck")
async def healthcheck():
    return Response()


@app.get("/")
async def read_main():
    logger.info("In root path")
    return {"msg": "Hello World"}


@app.post("/query")
async def process_query(request: QueryRequest):
    logger.info("Processing query")
    try:
        messages = await request.app.state.client.process_query(request.query)
        logger.info("Query processed successfully")
        return {"messages": messages}
    except Exception as e:
        logger.error("Error processing query", error=str(e))
        raise HTTPException(status_code=500, detail="Error processing query") from e
