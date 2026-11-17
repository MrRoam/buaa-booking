"""Offline demo fixtures. This module never calls a network client."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from buaa_booking.adapter import SubmitOutcome
from buaa_booking.config import CHINA
from src.parsers.day_info import parse_info_data


def demo_info(target: str, *, gap: bool = False):
    return parse_info_data({"reservationDateList": [target],
        "spaceTimeInfo": [{"id": 1, "beginTime": "19:00", "endTime": "20:00"},
                          {"id": 2, "beginTime": "21:00" if gap else "20:00", "endTime": "22:00" if gap else "21:00"}],
        "siteParam": {"venueSiteId": 38, "campusName": "学院路校区", "venueName": "体育馆主馆",
                      "siteName": "羽毛球", "buddyNumMin": 1, "buddyNumMax": 1},
        "orderParamView": {"phone": "", "buddyList": []},
        "reservationDateSpaceInfo": {target: [
            {"id": sid, "venueSiteId": 38, "spaceName": name,
             "1": {"reservationStatus": 1, "orderFee": 25},
             "2": {"reservationStatus": 1, "orderFee": 25}}
            for sid, name in ((101, "1号"), (102, "2号"))]}})


class DemoClock:
    def __init__(self, now: datetime | None = None):
        self.current = now or datetime.now(CHINA).replace(hour=7, minute=0, second=0, microsecond=0)
        self.tick = 0.0

    def now(self):
        return self.current

    def monotonic(self):
        return self.tick

    def sleep(self, seconds):
        self.current += timedelta(seconds=seconds)
        self.tick += seconds

    def wait_until(self, target):
        self.sleep(max(0, (target - self.current).total_seconds()))


class DemoAdapter:
    account_id = "offline-demo"

    def __init__(self, target: str, clock: DemoClock, scenario: str = "success"):
        self.info = demo_info(target)
        self.clock = clock
        self.scenario = scenario
        self.submissions = 0
        self.candidate = None

    def authenticate(self):
        pass

    def preflight(self):
        return self.info

    def warm(self):
        pass

    def query(self, target):
        return self.info

    def prepare(self, candidate, info):
        self.candidate = candidate
        return {}

    def submit(self, prepared):
        self.submissions += 1
        if self.scenario == "timeout":
            raise TimeoutError("DEMO: response lost after server accepted order")
        if self.scenario == "conflict" and self.submissions == 1:
            return SubmitOutcome("conflict", message="离线演示：首选场地已被占用")
        return SubmitOutcome("submitted", "DEMO-ORDER-NOT-REAL", "离线演示")

    def confirm(self, trade_no, candidate):
        return {"status": "pending_payment", "amount": str(candidate.price),
                "expire_time": (self.clock.now() + timedelta(minutes=10)).isoformat(),
                "message": "离线演示，不是真实订单；演示中的十分钟不代表官方付款时限"}

    def payment_link(self, trade_no):
        return ""
