"""New Member Interview: requirements by class, next-month meeting dates, and folder/file naming."""
import calendar
import re
from datetime import date

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

# class (lower case) -> (drills, meetings, hours_per_quarter or None)
#   hours_per_quarter set  -> the call box is "Hours per Quarter" with that value, whatever the response type
#   otherwise              -> Normal: "Call %" 10%   Duty Hours: "Hours" 288
CLASS_RULES = {
    "interior": ("16", "6", None),
    "exterior": ("16", "6", None),
    "junior": ("16", "6", None),
    "ems": ("8", "6", None),
    "driver": ("8", "6", None),
    "fire police": ("8", "6", None),
    "associate": ("NA", "6", "60"),
}
NORMAL_CALL_PERCENT = "10%"
DUTY_HOURS = "288"


class InterviewError(ValueError):
    """Something needed for the form is missing or not understood (message is shown to the user)."""


def requirements(membership_class, response_type):
    rule = CLASS_RULES.get((membership_class or "").strip().lower())
    if not (membership_class or "").strip():
        raise InterviewError("Choose a Membership Class first.")
    if rule is None:
        raise InterviewError(f"There are no interview requirements for the class '{membership_class}'.")
    drills, meetings, quarterly = rule
    if quarterly:
        label, value = "Hours per Quarter", quarterly
    else:
        rt = (response_type or "").strip().lower()
        if rt == "normal":
            label, value = "Call %", NORMAL_CALL_PERCENT
        elif rt == "duty hours":
            label, value = "Hours", DUTY_HOURS
        else:
            raise InterviewError("Choose a Response Type first (Normal or Duty Hours).")
    return {"drills": drills, "meetings": meetings, "call_label": label, "call_value": value}


def nth_weekday(year, month, weekday, n):
    """n-th (1-based) given weekday (Mon=0) of a month; n=-1 means the last one."""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if date(year, month, d).weekday() == weekday]
    return date(year, month, days[n - 1] if n > 0 else days[-1])


def next_month_dates(today):
    """First Thursday (membership), second Tuesday (commissioners) and last Wednesday (physical) of next month."""
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return {
        "membership": nth_weekday(year, month, 3, 1),
        "commissioners": nth_weekday(year, month, 1, 2),
        "physical": nth_weekday(year, month, 2, -1),
    }


def fmt_date(d):
    return f"{d:%m/%d/%y}"


def station_text(value):
    v = (value or "").strip()
    if not v:
        return ""
    return v if re.match(r"(?i)station\b", v) else f"Station {v}"


def address_text(m):
    street = " ".join((m["address"] or "").split())
    city = (m["city"] or "").strip()
    tail = " ".join(p for p in ((m["state"] or "").strip(), (m["zip"] or "").strip()) if p)
    city_part = ", ".join(p for p in (city, tail) if p)
    return " ".join(p for p in (street, city_part) if p)


def _clean(part):
    part = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", part or "")
    part = re.sub(r"\s+", "_", part.strip())
    return part.strip(". ")


def folder_name(member_id, last, first):
    """'<ID #>_<Last>_<First>'; with no ID # it starts with an underscore ('_Last_First')."""
    return f"{_clean(member_id)}_{_clean(last)}_{_clean(first)}".rstrip("_")


def file_name(last, first, today):
    return f"New_Member_Interview_{_clean(last)}_{_clean(first)}_{today:%Y-%m-%d}.pdf"
