"""Estimate the reservation website's HTTP clock, retaining its uncertainty."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from buaa_booking.config import CHINA

TIME_SOURCE = "https://cgyy.buaa.edu.cn/venue-server/api/front/website/init"


@dataclass(frozen=True)
class TimeSample:
    sent: float
    received: float
    server_second: float


def estimate(samples):
    """Date is whole seconds. Intersect bounds instead of claiming millisecond timestamps."""
    valid = [s for s in samples if 0 <= s.received - s.sent <= 2]
    if len(valid) < 3:
        raise RuntimeError("学校时间有效样本不足")
    lower = max(s.server_second - s.received for s in valid)
    upper = min(s.server_second + 1 - s.sent for s in valid)
    if lower > upper:
        raise RuntimeError("学校时间样本不一致，不能可靠校时")
    return (lower + upper) / 2, (upper - lower) / 2, min(s.received - s.sent for s in valid)


class SchoolClock:
    def __init__(self, directory: Path | None = None, *, probe=None,
                 wall_time=time.time, monotonic=time.monotonic, sleep=time.sleep):
        self.directory = directory
        self._wall_time = wall_time
        self.monotonic = monotonic
        self.sleep = sleep
        self.epoch_minus_tick = wall_time() - monotonic()
        self.probe = probe
        self.session = None
        self.receipt = None

    def now(self):
        return datetime.fromtimestamp(self.monotonic() + self.epoch_minus_tick, CHINA)

    def timestamp_ms(self):
        return int((self.monotonic() + self.epoch_minus_tick) * 1000)

    def _probe(self):
        import requests
        if self.session is None:
            self.session = requests.Session()
            self.session.trust_env = False
        sent = self.monotonic()
        response = self.session.get(TIME_SOURCE, params={"nocache": time.time_ns()},
                                    headers={"Cache-Control": "no-cache"}, timeout=3)
        received = self.monotonic()
        response.raise_for_status()
        if int(response.headers.get("Age", "0")) != 0 or not response.headers.get("Date"):
            raise RuntimeError("学校时间响应缺失或来自缓存")
        stamp = parsedate_to_datetime(response.headers["Date"]).timestamp()
        return TimeSample(sent, received, stamp)

    def synchronize(self, samples=8, interval=.18):
        observations = []
        for index in range(samples):
            try:
                observations.append((self.probe or self._probe)())
            except Exception:
                pass
            if index + 1 < samples:
                self.sleep(interval)
        epoch, uncertainty, rtt = estimate(observations)
        self.epoch_minus_tick = epoch
        self.receipt = {"source": TIME_SOURCE, "method": "http_date_interval_intersection",
                        "checked_at": self.now().isoformat(), "samples": len(observations),
                        "offset_ms": round((self.now().timestamp() - self._wall_time()) * 1000, 2),
                        "uncertainty_ms": round(uncertainty * 1000, 2), "best_rtt_ms": round(rtt * 1000, 2),
                        "limitation": "HTTP 网站时间参考，不是应用后台毫秒授时；网络路径与 HTTP Date 整秒精度仍有误差"}
        if self.directory:
            import json
            from buaa_booking.notify import atomic_text
            atomic_text(self.directory / "clock-sync.json", json.dumps(self.receipt, ensure_ascii=False, indent=2))
        return self.receipt

    def wait_until(self, target):
        target_tick = target.timestamp() - self.epoch_minus_tick
        while (remaining := target_tick - self.monotonic()) > 0:
            if remaining > 1:
                self.sleep(min(30, remaining - .25))
            elif remaining > .02:
                self.sleep(remaining - .01)
            else:
                self.sleep(min(.002, remaining))
