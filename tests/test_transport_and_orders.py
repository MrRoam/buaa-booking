from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from buaa_booking.adapter import classify_submission, verify_detail
from buaa_booking.demo import demo_info
from buaa_booking.selection import select_candidates
from src.http.base_client import BaseHttpClient
from src.parsers.order import OrderDetailParsed, OrderSpaceItem


def test_lost_post_response_is_never_replayed(monkeypatch):
    session = Mock()
    session.request.side_effect = requests.ReadTimeout("the server may already have committed")
    client = BaseHttpClient(session=session, retry_count=5)
    with pytest.raises(requests.ReadTimeout):
        client._request_with_retry("POST", "https://example.test/order", log_prefix="test")
    assert session.request.call_count == 1
    assert session.request.call_args.kwargs["timeout"] == 10.0


def test_read_request_can_retry_without_repeating_a_write(monkeypatch):
    monkeypatch.setattr("src.http.base_client.time.sleep", lambda _: None)
    response = Mock(status_code=200)
    session = Mock()
    session.request.side_effect = [requests.ConnectTimeout(), response]
    assert BaseHttpClient(session=session)._request_with_retry("GET", "https://example.test/info", log_prefix="test") is response
    assert session.request.call_count == 2


def test_http_4xx_is_not_blindly_retried(monkeypatch):
    response = Mock(status_code=403)
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    session = Mock()
    session.request.return_value = response
    with pytest.raises(requests.HTTPError):
        BaseHttpClient(session=session)._request_with_retry("GET", "https://example.test/info", log_prefix="test")
    assert session.request.call_count == 1


@pytest.mark.parametrize("raw,status", [
    ({"code": 200, "data": {"tradeNo": "D123"}}, "submitted"),
    ({"code": 200, "data": {}}, "unknown"),
    ({"code": 500, "message": "服务器内部错误"}, "unknown"),
    ({"code": 400, "message": "场地已被预约"}, "conflict"),
    ({"code": 400, "message": "同伴存在时间冲突"}, "rejected"),
    ({"code": 408, "message": "Token已失效，请重新登录"}, "rejected"),
    ({"code": 408, "message": "访问频繁"}, "rate_limited"),
    ({}, "unknown"),
])
def test_only_definite_conflicts_allow_switching(raw, status):
    assert classify_submission(raw).status == status


@pytest.fixture
def order(config, target):
    candidate = select_candidates(demo_info(str(target)), str(target), config)[0]
    detail = OrderDetailParsed(order_id=1, order_uuid="uuid", pay_user_id=1, order_status=1,
        pay_status=1, pay_fee=50, gmt_create="2026-10-16 07:00:01", expire_time="2026-10-16 07:05:01",
        subject="主馆羽毛球", subject_desc="", start_date="2026-10-18 19:00:00", end_date="2026-10-18 21:00:00",
        space_list=[OrderSpaceItem(i + 1, c.space_id, c.court, c.start, c.end, float(c.fee), "uuid")
                    for i, c in enumerate(candidate.choices)])
    return candidate, detail


def test_confirmation_uses_server_expiry_not_a_fixed_ten_minutes(order):
    candidate, detail = order
    result = verify_detail(detail, candidate)
    assert result["status"] == "pending_payment"
    assert result["expire_time"] == "2026-10-16 07:05:01"


@pytest.mark.parametrize("field,value", [("pay_fee", 55), ("start_date", "2026-10-19 19:00:00"),
                                        ("end_date", "2026-10-18 22:00:00")])
def test_mismatched_order_is_never_reported_as_confirmed(order, field, value):
    candidate, detail = order
    setattr(detail, field, value)
    assert verify_detail(detail, candidate)["status"] == "needs_review"


def test_wrong_court_and_payment_states(order):
    candidate, detail = order
    detail.space_list[0].venue_space_id = 999
    assert verify_detail(detail, candidate)["status"] == "needs_review"
    detail.space_list[0].venue_space_id = candidate.choices[0].space_id
    detail.pay_status = 2
    assert verify_detail(detail, candidate)["status"] == "paid"
    detail.order_status = 2
    assert verify_detail(detail, candidate)["status"] == "cancelled"


@pytest.mark.parametrize("order_status,pay_status,expected", [
    (1, 1, "pending_payment"), (1, 2, "paid"), (2, 1, "cancelled"),
    (2, 3, "refunding"), (2, 4, "refunded"), (2, 5, "refund_failed"),
    (0, 0, "needs_review"), (1, 0, "needs_review"), (3, 2, "needs_review"),
])
def test_official_payment_enum_is_not_a_boolean(order, order_status, pay_status, expected):
    candidate, detail = order
    detail.order_status, detail.pay_status = order_status, pay_status
    assert verify_detail(detail, candidate)["status"] == expected


def test_get_timeout_can_be_tighter_without_changing_post_timeout():
    response = Mock(status_code=200)
    session = Mock()
    session.request.return_value = response
    client = BaseHttpClient(session=session, get_timeout_sec=3.5)
    client._request_with_retry("GET", "https://example.test/info", log_prefix="test")
    assert session.request.call_args.kwargs["timeout"] == 3.5
    client._request_with_retry("POST", "https://example.test/order", log_prefix="test")
    assert session.request.call_args.kwargs["timeout"] == 10.0


def test_empty_json_query_response_refreshes_auth_then_raises_transient(config):
    import json
    from buaa_booking.adapter import LiveAdapter, TransientQueryError
    adapter = object.__new__(LiveAdapter)
    adapter.config = config
    adapter.authenticate = Mock()
    adapter.api = Mock()
    adapter.api.get_info.side_effect = json.JSONDecodeError("Expecting value", "", 0)
    with pytest.raises(TransientQueryError):
        adapter.query("2026-11-19")
    adapter.authenticate.assert_called_once()
    assert adapter.api.get_info.call_count == 2
