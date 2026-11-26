"""Individual interview times: daily windows, breaks and no overlap for one validator.

Times are naive datetimes in Dakar time, which is UTC all year round.
"""

from datetime import date, datetime, time, timedelta
import re

from app.services.interviews.exceptions import InterviewValidationError


MAX_DAYS = 366
MAX_BREAKS = 5
LEGACY_MINUTES = 10
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _clock(value, label):
    if not isinstance(value, str) or not _CLOCK.match(value):
        raise InterviewValidationError(f"{label} : utilisez le format HH:MM.")
    hours, minutes = map(int, value.split(":"))
    return time(hours, minutes)


def _minutes(value):
    return value.hour * 60 + value.minute


def normalize_schedule(data):
    if not isinstance(data, dict):
        raise InterviewValidationError("Renseignez les horaires des entretiens.")
    try:
        start_date = date.fromisoformat(data.get("start_date") or "")
    except (TypeError, ValueError) as error:
        raise InterviewValidationError("Indiquez la date de début des entretiens.") from error
    day_start = _clock(data.get("day_start"), "Heure de début")
    day_end = _clock(data.get("day_end"), "Heure de fin")
    if day_end <= day_start:
        raise InterviewValidationError("L’heure de fin doit être après l’heure de début.")
    duration = data.get("duration")
    if type(duration) is not int or not 5 <= duration <= 180:
        raise InterviewValidationError("La durée d’un entretien doit être comprise entre 5 et 180 minutes.")
    if _minutes(day_end) - _minutes(day_start) < duration:
        raise InterviewValidationError("La plage horaire est plus courte qu’un entretien.")
    raw_breaks = data.get("breaks", [])
    if not isinstance(raw_breaks, list) or len(raw_breaks) > MAX_BREAKS:
        raise InterviewValidationError(f"Indiquez au plus {MAX_BREAKS} pauses.")
    breaks = []
    for item in raw_breaks:
        if not isinstance(item, dict):
            raise InterviewValidationError("Pause invalide.")
        start = _clock(item.get("start"), "Début de pause")
        end = _clock(item.get("end"), "Fin de pause")
        if end <= start or start < day_start or end > day_end:
            raise InterviewValidationError("Chaque pause doit se situer dans la plage horaire, avec une fin après son début.")
        breaks.append({"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
    breaks.sort(key=lambda item: item["start"])
    skip_weekends = data.get("skip_weekends", True)
    if type(skip_weekends) is not bool:
        raise InterviewValidationError("Option week-end invalide.")
    return {
        "start_date": start_date.isoformat(), "day_start": day_start.strftime("%H:%M"), "day_end": day_end.strftime("%H:%M"),
        "duration": duration, "breaks": breaks, "skip_weekends": skip_weekends,
    }


def _round_up(value, step=5):
    value = value.replace(second=0, microsecond=0)
    remainder = value.minute % step
    return value + timedelta(minutes=step - remainder) if remainder else value


def plan_times(schedule, busy, count, now):
    """Return `count` start times that avoid breaks, the past and the validator's busy intervals."""
    if count <= 0:
        return []
    duration = timedelta(minutes=schedule["duration"])
    day = date.fromisoformat(schedule["start_date"])
    day_start = time.fromisoformat(schedule["day_start"])
    day_end = time.fromisoformat(schedule["day_end"])
    breaks = [(time.fromisoformat(item["start"]), time.fromisoformat(item["end"])) for item in schedule["breaks"]]
    earliest = _round_up(now)
    times = []
    for _ in range(MAX_DAYS):
        if len(times) >= count:
            break
        if not (schedule["skip_weekends"] and day.weekday() >= 5):
            cursor = max(datetime.combine(day, day_start), earliest)
            end = datetime.combine(day, day_end)
            blocked = [(datetime.combine(day, start), datetime.combine(day, stop)) for start, stop in breaks]
            blocked += [(start, stop) for start, stop in busy if start < end and stop > cursor]
            while len(times) < count and cursor + duration <= end:
                clash = next((stop for start, stop in blocked if start < cursor + duration and cursor < stop), None)
                if clash:
                    cursor = clash
                    continue
                times.append(cursor)
                cursor += duration
        day += timedelta(days=1)
    if len(times) < count:
        raise InterviewValidationError(
            "Les horaires ne permettent pas de planifier tous les candidats sur une année. "
            "Élargissez la plage horaire ou réduisez la durée des entretiens."
        )
    return times


def validator_intervals(distribution, user_id):
    """Busy intervals of a validator inside one referential workspace."""
    item = (distribution.get("validators") or {}).get(user_id)
    if not item:
        return []
    slots = item.get("slots") or {}
    intervals = []
    for value in slots.values():
        start = datetime.fromisoformat(value["at"])
        intervals.append((start, start + timedelta(minutes=value["minutes"])))
    legacy = [candidate for candidate in item.get("candidates", []) if candidate not in slots]
    if legacy and distribution.get("starts_at"):
        start = datetime.fromisoformat(distribution["starts_at"])
        intervals.append((start, start + timedelta(minutes=LEGACY_MINUTES * len(legacy))))
    return intervals
