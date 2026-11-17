from unittest.mock import Mock

import pytest

from src.config.settings import ApiSettings, UserSettings
from src.core.captcha_service import CaptchaService
from src.core.exceptions import CaptchaError
from src.core.workflow import ReservationWorkflow


def test_server_captcha_limit_stops_after_first_reply():
    service = object.__new__(CaptchaService)
    service.api = Mock()
    service.api.get_captcha_raw.return_value = {'code': 250, 'message': '验证码次数超出限制，请稍后再操作！'}
    workflow = ReservationWorkflow(service, None, 0, 0, ApiSettings(captcha_refetch_count=3), UserSettings())
    with pytest.raises(CaptchaError):
        workflow._verify_captcha_with_retry()
    assert service.api.get_captcha_raw.call_count == 1


def test_exhausted_shared_fetch_budget_does_not_request_another_challenge():
    service = object.__new__(CaptchaService)
    service.api = Mock()
    service.fetch_budget = 0
    with pytest.raises(CaptchaError):
        service.fetch_captcha()
    service.api.get_captcha_raw.assert_not_called()
