
import logging
import os
import time
from itertools import count
from threading import Lock
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(message)s",
)
logger = logging.getLogger("orders-api")

app = FastAPI(
    title="DevOps Orders API",
    version=os.getenv("APP_VERSION", "1.0.0"),
)

REQUESTS = Counter(
    "orders_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "orders_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
ORDERS_CREATED = Counter(
    "orders_created_total",
    "Total orders created",
)
ORDERS_STORED = Gauge(
    "orders_stored",
    "Number of orders stored in process memory",
)

orders = []
order_ids = count(1)
orders_lock = Lock()


class OrderInput(BaseModel):
    product: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=1000)
    status: Literal["pending", "confirmed"] = "pending"


class Order(OrderInput):
    id: int


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500

    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        path = request.url.path
        # Avoid high-cardinality labels for parameterized routes.
        if path.startswith("/orders/"):
            path = "/orders/{id}"

        REQUESTS.labels(
            request.method, path, str(status)
        ).inc()
        LATENCY.labels(request.method, path).observe(
            time.perf_counter() - start
        )

        logger.info(
            '{"event":"http_request","method":"%s",'
            '"path":"%s","status":%d}',
            request.method,
            path,
            status,
        )


@app.get("/")
def root():
    return {
        "application": "devops-orders-api",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "environment": os.getenv("APP_ENV", "local"),
    }


@app.get("/health")
def health():
    return {"status": "alive"}


@app.get("/ready")
def ready():
    # Add database/dependency checks here when a database is introduced.
    return {"status": "ready"}


@app.get("/orders", response_model=list[Order])
def list_orders():
    with orders_lock:
        return list(orders)


@app.post("/orders", response_model=Order, status_code=201)
def create_order(payload: OrderInput):
    with orders_lock:
        order = Order(id=next(order_ids), **payload.model_dump())
        orders.append(order)
        ORDERS_CREATED.inc()
        ORDERS_STORED.set(len(orders))

    logger.info('{"event":"order_created","order_id":%d}', order.id)
    return order


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int):
    with orders_lock:
        order = next(
            (item for item in orders if item.id == order_id),
            None,
        )

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
