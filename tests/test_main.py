from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["application"] == "devops-orders-api"


def test_health_and_ready():
    assert client.get("/health").json()["status"] == "alive"
    assert client.get("/ready").json()["status"] == "ready"


def test_create_and_read_order():
    created = client.post(
        "/orders",
        json={"product": "keyboard", "quantity": 2},
    )
    assert created.status_code == 201

    order = created.json()
    assert order["product"] == "keyboard"
    assert order["quantity"] == 2

    fetched = client.get(f"/orders/{order['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == order["id"]


def test_invalid_order():
    response = client.post(
        "/orders",
        json={"product": "", "quantity": -1},
    )
    assert response.status_code == 422


def test_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "orders_http_requests_total" in response.text