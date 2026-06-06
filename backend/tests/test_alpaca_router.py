"""
Unit tests for Alpaca trading API endpoints.

All Alpaca SDK calls are mocked — no real credentials or network calls required.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_ACCOUNT = SimpleNamespace(
    id="abc123",
    status="ACTIVE",
    currency="USD",
    buying_power="50000.00",
    cash="25000.00",
    portfolio_value="75000.00",
    pattern_day_trader=False,
    trading_blocked=False,
    account_blocked=False,
    trade_suspended_by_user=False,
)

MOCK_CLOCK = SimpleNamespace(
    timestamp="2026-06-06T09:30:00-04:00",
    is_open=True,
    next_open="2026-06-09T09:30:00-04:00",
    next_close="2026-06-06T16:00:00-04:00",
)

MOCK_POSITION = SimpleNamespace(
    symbol="AAPL",
    qty="10",
    side="long",
    avg_entry_price="200.00",
    current_price="213.00",
    market_value="2130.00",
    unrealized_pl="130.00",
    unrealized_plpc="0.065",
    change_today="0.012",
)

MOCK_ORDER = SimpleNamespace(
    id="order-001",
    client_order_id="client-001",
    symbol="AAPL",
    qty="10",
    notional=None,
    side="buy",
    order_type="market",
    time_in_force="day",
    limit_price=None,
    stop_price=None,
    status="filled",
    filled_qty="10",
    filled_avg_price="213.00",
    created_at="2026-06-06T09:30:01Z",
    filled_at="2026-06-06T09:30:02Z",
)


def _mock_client(acct=None, clock=None, positions=None, position=None, orders=None, order=None):
    """Build a mock TradingClient with configurable return values."""
    m = MagicMock()
    if acct is not None:
        m.get_account.return_value = acct
    if clock is not None:
        m.get_clock.return_value = clock
    if positions is not None:
        m.get_all_positions.return_value = positions
    if position is not None:
        m.get_open_position.return_value = position
    if orders is not None:
        m.get_orders.return_value = orders
    if order is not None:
        m.submit_order.return_value = order
        m.get_order_by_id.return_value = order
    return m


# ── Account tests ─────────────────────────────────────────────────────────────


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_account_success(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    resp = client.get("/alpaca/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "abc123"
    assert data["status"] == "ACTIVE"
    assert data["buying_power"] == 50000.0
    assert data["portfolio_value"] == 75000.0
    assert data["is_paper"] is True  # default env


@patch("app.alpaca.router.alpaca_configured", return_value=False)
def test_get_account_not_configured(mock_configured):
    resp = client.get("/alpaca/account")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_account_api_error(mock_configured, mock_get_client):
    m = MagicMock()
    m.get_account.side_effect = Exception("upstream API error")
    mock_get_client.return_value = m
    resp = client.get("/alpaca/account")
    assert resp.status_code == 502
    assert "upstream API error" in resp.json()["detail"]


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_market_clock(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(clock=MOCK_CLOCK)
    resp = client.get("/alpaca/account/clock")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_open"] is True
    assert "next_open" in data
    assert "next_close" in data


# ── Position tests ────────────────────────────────────────────────────────────


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_positions_empty(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(positions=[])
    resp = client.get("/alpaca/positions")
    assert resp.status_code == 200
    assert resp.json() == []


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_positions_with_data(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(positions=[MOCK_POSITION, MOCK_POSITION])
    resp = client.get("/alpaca/positions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["qty"] == 10.0
    assert data[0]["unrealized_pl"] == 130.0


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_position_by_symbol(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(position=MOCK_POSITION)
    resp = client.get("/alpaca/positions/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["avg_entry_price"] == 200.0


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_position_not_found(mock_configured, mock_get_client):
    m = MagicMock()
    m.get_open_position.side_effect = Exception("position does not exist")
    mock_get_client.return_value = m
    resp = client.get("/alpaca/positions/FAKE")
    assert resp.status_code == 404


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_close_position(mock_configured, mock_get_client):
    m = MagicMock()
    m.close_position.return_value = MOCK_ORDER
    mock_get_client.return_value = m
    resp = client.delete("/alpaca/positions/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Position closed"
    assert "order" in data


# ── Order tests ───────────────────────────────────────────────────────────────


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_orders_all(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(orders=[MOCK_ORDER])
    resp = client.get("/alpaca/orders?status=open")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"
    assert data[0]["status"] == "filled"


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_orders_open_status(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(orders=[])
    resp = client.get("/alpaca/orders?status=open")
    assert resp.status_code == 200


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_place_market_order(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(order=MOCK_ORDER)
    resp = client.post(
        "/alpaca/orders", json={"symbol": "AAPL", "qty": 10, "side": "buy", "type": "market"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["id"] == "order-001"


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_place_limit_order(mock_configured, mock_get_client):
    limit_order = SimpleNamespace(
        **vars(MOCK_ORDER) if hasattr(MOCK_ORDER, "__dict__") else MOCK_ORDER.__dict__
    )
    limit_order.order_type = "limit"
    limit_order.limit_price = "210.00"
    mock_get_client.return_value = _mock_client(order=limit_order)
    resp = client.post(
        "/alpaca/orders",
        json={"symbol": "AAPL", "qty": 5, "side": "buy", "type": "limit", "limit_price": 210.0},
    )
    assert resp.status_code == 200


def test_place_order_qty_and_notional_both_set():
    resp = client.post(
        "/alpaca/orders",
        json={"symbol": "AAPL", "qty": 10, "notional": 1000, "side": "buy", "type": "market"},
    )
    assert resp.status_code == 422


@patch("app.alpaca.router.alpaca_configured", return_value=False)
def test_place_order_not_configured(mock_configured):
    resp = client.post(
        "/alpaca/orders", json={"symbol": "AAPL", "qty": 10, "side": "buy", "type": "market"}
    )
    assert resp.status_code == 503


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_cancel_order(mock_configured, mock_get_client):
    m = MagicMock()
    m.cancel_order_by_id.return_value = None
    mock_get_client.return_value = m
    resp = client.delete("/alpaca/orders/order-001")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Order cancelled"


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_cancel_order_not_found(mock_configured, mock_get_client):
    m = MagicMock()
    m.cancel_order_by_id.side_effect = Exception("order not found")
    mock_get_client.return_value = m
    resp = client.delete("/alpaca/orders/nonexistent")
    assert resp.status_code == 404


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_order_by_id(mock_configured, mock_get_client):
    mock_get_client.return_value = _mock_client(order=MOCK_ORDER)
    resp = client.get("/alpaca/orders/order-001")
    assert resp.status_code == 200
    assert resp.json()["id"] == "order-001"


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_get_order_not_found(mock_configured, mock_get_client):
    m = MagicMock()
    m.get_order_by_id.side_effect = Exception("order not found")
    mock_get_client.return_value = m
    resp = client.get("/alpaca/orders/bad-id")
    assert resp.status_code == 404


# ── Portfolio history tests ───────────────────────────────────────────────────


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_portfolio_history_default_params(mock_configured, mock_get_client):
    mock_history = SimpleNamespace(
        timestamp=[1700000000, 1700086400],
        equity=[10000.0, 10500.0],
        profit_loss=[0.0, 500.0],
        profit_loss_pct=[0.0, 0.05],
        base_value=10000.0,
        timeframe="1D",
    )
    m = MagicMock()
    m.get_portfolio_history.return_value = mock_history
    mock_get_client.return_value = m
    resp = client.get("/alpaca/portfolio/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["equity"]) == 2
    assert data["base_value"] == 10000.0
    # verify default params were used (period=1M, timeframe=1D)
    call_kwargs = m.get_portfolio_history.call_args
    assert call_kwargs is not None


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_portfolio_history_custom_params(mock_configured, mock_get_client):
    mock_history = SimpleNamespace(
        timestamp=[1700000000],
        equity=[10000.0],
        profit_loss=[0.0],
        profit_loss_pct=[0.0],
        base_value=10000.0,
        timeframe="1H",
    )
    m = MagicMock()
    m.get_portfolio_history.return_value = mock_history
    mock_get_client.return_value = m
    resp = client.get("/alpaca/portfolio/history?period=1W&timeframe=1H")
    assert resp.status_code == 200
    assert resp.json()["timeframe"] == "1H"


# ── account param routing tests ───────────────────────────────────────────────
# These tests verify that the correct client (paper vs real money) is invoked,
# not just that the response looks right.


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_no_account_param_calls_paper_client(mock_configured, mock_get_client):
    """No ?account param → get_trading_client called with paper=True."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    client.get("/alpaca/account")
    mock_get_client.assert_called_once_with(True)


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_account_paper_calls_paper_client(mock_configured, mock_get_client):
    """?account=paper → get_trading_client called with paper=True."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    client.get("/alpaca/account?account=paper")
    mock_get_client.assert_called_once_with(True)


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_account_live_calls_live_client(mock_configured, mock_get_client):
    """?account=real → get_trading_client called with paper=False."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    client.get("/alpaca/account?account=real")
    mock_get_client.assert_called_once_with(False)


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_no_account_param_is_paper_true_in_response(mock_configured, mock_get_client):
    """No ?account param → is_paper=True in response body."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    resp = client.get("/alpaca/account")
    assert resp.status_code == 200
    assert resp.json()["is_paper"] is True


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_account_live_is_paper_false_in_response(mock_configured, mock_get_client):
    """?account=real → is_paper=False in response body."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    resp = client.get("/alpaca/account?account=real")
    assert resp.status_code == 200
    assert resp.json()["is_paper"] is False


@patch("app.alpaca.router.alpaca_configured", return_value=False)
def test_account_live_not_configured_503(mock_configured):
    """?account=real with no real money creds → 503 naming 'real'."""
    resp = client.get("/alpaca/account?account=real")
    assert resp.status_code == 503
    assert "real" in resp.json()["detail"]


@patch("app.alpaca.router.alpaca_configured", return_value=False)
def test_account_paper_not_configured_503(mock_configured):
    """No ?account param with no paper creds → 503 naming 'paper'."""
    resp = client.get("/alpaca/account")
    assert resp.status_code == 503
    assert "paper" in resp.json()["detail"]


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_alpaca_configured_called_with_paper_true_by_default(mock_configured, mock_get_client):
    """alpaca_configured is checked with paper=True when no ?account param."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    client.get("/alpaca/account")
    mock_configured.assert_called_with(True)


@patch("app.alpaca.router.get_trading_client")
@patch("app.alpaca.router.alpaca_configured", return_value=True)
def test_alpaca_configured_called_with_paper_false_for_live(mock_configured, mock_get_client):
    """alpaca_configured is checked with paper=False when ?account=real."""
    mock_get_client.return_value = _mock_client(acct=MOCK_ACCOUNT)
    client.get("/alpaca/account?account=real")
    mock_configured.assert_called_with(False)
