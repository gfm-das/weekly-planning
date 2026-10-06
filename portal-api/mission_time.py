"""The mission's time zone: where "today", the week's Sunday, the Sunday 18:00 reminders and the times people see are counted.

It is a setting, GFM_TIME_ZONE in portal-api/.env (an IANA name such as America/Denver). When nothing is set it is Europe/Berlin, as
it always was. A wrong name stops the program at start (ZoneInfoNotFoundError), not later in the middle of a request.
The database counts in the same zone: public.gfm_time_zone() (migration 045) reads it from the mission's row.
"""
import os
from zoneinfo import ZoneInfo

NAME = (os.environ.get('GFM_TIME_ZONE') or 'Europe/Berlin').strip()
ZONE = ZoneInfo(NAME)
