from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass
from decimal import Decimal

from buaa_booking.config import Config, minutes
from src.parsers.day_info import DayInfoParsed


def court_key(name: str) -> str:
    digits = re.fullmatch(r"(?:羽毛球)?\s*0*(\d+)\s*号?", name)
    return digits.group(1) if digits else name.strip()


@dataclass(frozen=True)
class Choice:
    space_id: int
    time_id: int
    court: str
    start: str
    end: str
    fee: str


@dataclass(frozen=True)
class Candidate:
    date: str
    venue_site_id: int
    preference: int
    choices: tuple[Choice, ...]

    @property
    def price(self) -> Decimal:
        return sum((Decimal(c.fee) for c in self.choices), Decimal("0"))

    @property
    def key(self) -> tuple:
        return tuple((c.space_id, c.time_id) for c in self.choices)

    def to_dict(self) -> dict:
        return asdict(self) | {"price": str(self.price)}


def select_candidates(info: DayInfoParsed, target: str, config: Config) -> list[Candidate]:
    # Never use reservationDateList[0]: it can be a different day.
    if info.site_param and info.site_param.venue_site_id != config.venue_site_id:
        raise ValueError("服务器返回的场馆与配置不一致")
    schedules = info.space_schedules_by_date.get(target, [])
    results: list[Candidate] = []
    seen: set[tuple] = set()
    for rank, pref in enumerate(config.preferences):
        slots = sorted((s for s in info.time_slots if minutes(pref.start) <= minutes(s.begin_time)
                        and minutes(s.end_time) <= minutes(pref.end)), key=lambda s: s.begin_time)
        # Actual wall-clock adjacency, not neighboring array indices.
        if not slots or slots[0].begin_time != pref.start or slots[-1].end_time != pref.end:
            continue
        if any(minutes(s.end_time) <= minutes(s.begin_time) for s in slots):
            continue
        if any(a.end_time != b.begin_time for a, b in zip(slots, slots[1:])):
            continue
        allowed = [court_key(c) for c in pref.courts]
        spaces = [s for s in schedules if s.venue_site_id == config.venue_site_id
                  and (not allowed or court_key(s.space_name) in allowed or pref.allow_other_courts)]
        spaces.sort(key=lambda s: (allowed.index(court_key(s.space_name))
                                  if court_key(s.space_name) in allowed else len(allowed),
                                  int(court_key(s.space_name)) if court_key(s.space_name).isdigit() else 999,
                                  s.space_name))
        available = [[space for space in spaces if (st := space.slots.get(str(slot.id))) and st.is_available]
                     for slot in slots]
        if not all(available):
            continue
        if config.same_court:
            combinations = ((s,) * len(slots) for s in spaces if all(s in group for group in available))
        else:
            combinations = itertools.product(*available)
        for combo in combinations:
            choices = tuple(Choice(s.space_id, t.id, s.space_name, t.begin_time, t.end_time,
                                   str(s.slots[str(t.id)].order_fee)) for s, t in zip(combo, slots))
            candidate = Candidate(target, config.venue_site_id, rank, choices)
            if not all(Decimal(c.fee).is_finite() and Decimal(c.fee) >= 0 for c in choices):
                continue
            if candidate.price > config.max_total_price or candidate.key in seen:
                continue
            if candidate.price != candidate.price.to_integral_value():
                # Upstream orderPrice is integer yuan. Do not silently round a real price.
                continue
            seen.add(candidate.key)
            results.append(candidate)
            if len(results) >= 256:
                return results
    return results
