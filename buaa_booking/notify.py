from __future__ import annotations

import base64
import html
import json
import os
import smtplib
import ssl
import subprocess
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from buaa_booking.config import CHINA

LABELS = {"pending_payment": "预约已确认，请付款", "paid": "已付款", "submitted": "已取得订单号，请核对",
          "captcha_invalid": "验证码被拒绝，未取得订单", "release_not_open": "学校尚未开放预约",
          "rejected": "预约被拒绝，未取得订单", "conflict": "场地已被占用", "rate_limited": "预约接口要求稍后重试",
          "refunding": "退款处理中", "refunded": "已退款", "refund_failed": "退款失败，请检查官方订单",
          "unknown": "提交结果待核对", "needs_review": "订单需要核对", "cancelled": "订单已取消",
          "deadline_passed": "付款截止时间已过", "finished": "本次未预约成功", "missed": "已错过抢场窗口",
          "dry_run": "查询验证通过，未下单", "rehearsed": "提交前演练通过，未下单",
          "no_availability": "暂无符合条件的空场", "error": "运行未完成", "test": "通知测试"}


def safe_payment_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443):
            if host == "buaa.edu.cn" or host.endswith(".buaa.edu.cn") or host == "cashier.cc-pay.cn":
                return value
    except ValueError:
        pass
    return "https://cgyy.buaa.edu.cn/venue/home"


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def order_message(record: dict) -> str:
    candidate = record.get("candidate", {})
    choices = candidate.get("choices", [])
    lines = [LABELS.get(record.get("status"), record.get("status", ""))]
    if record.get("demo"):
        lines.insert(0, "离线演示，不是真实订单")
    if choices:
        lines.append(f"{candidate['date']} {'主馆' if candidate['venue_site_id'] == 38 else '副馆'} "
                     f"{choices[0]['start']}–{choices[-1]['end']}")
        lines.append("场地：" + "、".join(dict.fromkeys(c["court"] for c in choices)))
        lines.append("总金额：¥" + candidate["price"])
    if record.get("trade_no"):
        lines.append("订单号：" + record["trade_no"])
    if record.get("expire_time"):
        lines.append("付款截止：" + record["expire_time"] + "（北京时间）")
    if record.get("message"):
        lines.append(record["message"])
    return "\n".join(lines)


def write_order_page(directory: Path, record: dict):
    directory.mkdir(parents=True, exist_ok=True)
    escaped = html.escape(order_message(record))
    link = html.escape(safe_payment_url(record.get("payment_url", "")), quote=True)
    title = "离线演示，不是真实订单" if record.get("demo") else LABELS.get(record.get("status"), "预约结果")
    button = (f'<a href="{link}" target="_blank" rel="noopener noreferrer">打开官方付款页面</a>'
              if not record.get("demo") and record.get("status") in {"pending_payment", "submitted", "unknown", "needs_review"}
              else "")
    expiry = ""
    try:
        dt = datetime.fromisoformat(record.get("expire_time", "").replace("Z", "+00:00"))
        expiry = (dt.replace(tzinfo=CHINA) if dt.tzinfo is None else dt).isoformat()
    except ValueError:
        pass
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f4f5f7;color:#162b2a;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:640px;margin:8vh auto;background:white;padding:36px;border-radius:16px}}h1{{font-size:26px;line-height:1.4}}
pre{{white-space:pre-wrap;font:inherit}}a{{display:inline-block;background:#075e52;color:white;padding:12px 20px;
border-radius:8px;text-decoration:none}}small{{color:#5e6b69}}@media(max-width:700px){{main{{margin:16px;padding:24px}}}}</style>
<main><small>北航学院路羽毛球预约</small><h1>{html.escape(title)}</h1><pre>{escaped}</pre><p id="countdown"></p>{button}
<p><small>付款和最终订单状态以官方系统为准。此页不会执行付款。</small></p></main>
<script>const end={json.dumps(expiry)};const active={json.dumps(record.get('status') == 'pending_payment' and not record.get('demo'))};
function tick(){{if(!end||!active)return;const n=Math.ceil((Date.parse(end)-Date.now())/1000);
document.getElementById('countdown').textContent=n>0?'距付款截止还有 '+Math.floor(n/60)+' 分 '+n%60+' 秒':'付款截止时间已过，请检查官方订单';}}
tick();setInterval(tick,1000);</script></html>'''
    atomic_text(directory / "latest-order.html", page)
    atomic_text(directory / "latest-result.json", json.dumps(record, ensure_ascii=False, indent=2))


def desktop_notification(title: str, body: str) -> bool:
    if os.name != "nt":
        return False
    # User/server text travels as data, never as PowerShell source.
    script = '''[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null
$doc=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes=$doc.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($doc.CreateTextNode($env:BUAA_TOAST_TITLE)) > $null
$nodes.Item(1).AppendChild($doc.CreateTextNode($env:BUAA_TOAST_BODY)) > $null
$toast=[Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.Windows.PowerShell').Show($toast)'''
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, BUAA_TOAST_TITLE=title, BUAA_TOAST_BODY=body)
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                             "-EncodedCommand", encoded], env=env, capture_output=True, timeout=8,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.returncode == 0


class Notifier:
    def __init__(self, directory: Path, channels: dict, secrets: dict | None = None, *, open_payment: bool = False):
        self.directory = directory
        self.channels = channels
        self.secrets = secrets or {}
        self.open_payment = open_payment
        self.opened_trades = set()

    def __call__(self, record: dict, *, external: bool = True):
        write_order_page(self.directory, record)
        if not external or record.get("demo"):
            return
        trade = record.get("trade_no")
        if self.open_payment and record.get("status") == "pending_payment" and trade and trade not in self.opened_trades:
            # The one-minute checkout window starts on the server. Open before slower channels.
            self.opened_trades.add(trade)
            try:
                import webbrowser
                webbrowser.open(safe_payment_url(record.get("payment_url", "")))
            except Exception:
                pass  # Notification and local payment page remain available.
        message = order_message(record)
        title = "北航预约 · " + LABELS.get(record.get("status"), "运行结果")
        results = {}
        for channel in ("desktop", "bark", "email"):
            if not self.channels.get(channel, False):
                results[channel] = "disabled"
                continue
            try:
                sent = self.send(channel, title, message, record.get("payment_url", ""))
                results[channel] = "sent" if sent else "not_configured_or_unavailable"
            except Exception as exc:
                # Do not record endpoint URLs, passwords or server error bodies.
                results[channel] = "failed:" + type(exc).__name__
        atomic_text(self.directory / "notification-status.json", json.dumps(results, ensure_ascii=False, indent=2))

    def send(self, channel: str, title: str, body: str, url: str) -> bool:
        if channel == "desktop":
            return desktop_notification(title, body)
        if channel == "bark":
            if not self.secrets.get("bark_key"):
                return False
            import requests
            with requests.Session() as session:
                session.trust_env = False
                response = session.post("https://api.day.app/push", json={
                    "device_key": self.secrets["bark_key"], "title": title, "body": body,
                    "group": "北航预约", "sound": "alarm", "url": safe_payment_url(url)}, timeout=5)
                response.raise_for_status()
                return response.json().get("code") == 200
        if channel == "email":
            required = ("smtp_host", "smtp_username", "smtp_password", "email_to")
            if not all(self.secrets.get(k) for k in required):
                return False
            msg = EmailMessage()
            msg["Subject"] = title
            msg["From"] = self.secrets["smtp_username"]
            msg["To"] = self.secrets["email_to"]
            msg.set_content(body + "\n" + safe_payment_url(url))
            port = int(self.secrets.get("smtp_port", 465))
            if port == 465:
                connection = smtplib.SMTP_SSL(self.secrets["smtp_host"], port, timeout=8,
                                              context=ssl.create_default_context())
            else:
                connection = smtplib.SMTP(self.secrets["smtp_host"], port, timeout=8)
                connection.starttls(context=ssl.create_default_context())
            with connection:
                connection.login(self.secrets["smtp_username"], self.secrets["smtp_password"])
                connection.send_message(msg)
            return True
        return False
