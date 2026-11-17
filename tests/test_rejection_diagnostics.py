from buaa_booking.adapter import classify_submission
import pytest


@pytest.mark.parametrize('raw,status,reason', [
    ({'code': 250, 'data': {'repMsg': '场地已被预约'}}, 'conflict', '场地已被预约'),
    ({'code': 511, 'message': '请重新验证'}, 'captcha_invalid', '请重新验证'),
    ({'code': 250, 'message': '验证码已失效，请重新验证'}, 'captcha_invalid', '验证码已失效'),
    ({'code': 250, 'message': '未到预约时间'}, 'release_not_open', '未到预约时间'),
    ({'code': 250, 'message': '同伴存在时间冲突'}, 'rejected', '同伴存在时间冲突'),
    ({'code': 500, 'message': '场地已被预约'}, 'unknown', '场地已被预约'),
    ({'code': 250, 'data': {'tradeNo': 'ORDER'}, 'message': '验证码失效'}, 'unknown', '验证码失效'),
])
def test_classification_preserves_reason_and_only_retries_explicit_refusals(raw, status, reason):
    outcome = classify_submission(raw)
    assert outcome.status == status
    assert reason in outcome.message
    assert outcome.server_code == str(raw['code'])


def test_business_rejection_keeps_the_reason_instead_of_only_code():
    result = classify_submission({'code': 250, 'message': '验证码已失效，请重新验证'})
    assert result.status == 'captcha_invalid'
    assert '验证码已失效' in result.message
    assert '250' in result.message


def test_server_explanation_does_not_expose_embedded_credentials():
    result = classify_submission({'code': 250,
        'message': '验证失败，学号20000001，手机13800138000，令牌abcdefghijklmnopqrstuvwx，https://example.test/pay?token=secret'})
    assert '20000001' not in result.message
    assert '13800138000' not in result.message
    assert 'abcdefghijklmnopqrstuvwx' not in result.message
    assert 'token=secret' not in result.message


def test_diagnostics_survive_restart_and_can_be_read_without_credentials(config, tmp_path, monkeypatch, capsys):
    from buaa_booking.journal import Journal
    from buaa_booking.__main__ import main
    from buaa_booking.vault import Vault
    directory = config.path.parent / 'data'
    journal = Journal(directory)
    journal.trace('test', 'submit_result', server_code='250', message='验证码失效')
    journal.close()
    monkeypatch.setattr(Vault, 'read', lambda _: pytest.fail('diagnostics must not read credentials'))
    assert main(['--config', str(config.path), 'diagnostics']) == 0
    output = capsys.readouterr().out
    assert '250' in output and '验证码失效' in output
