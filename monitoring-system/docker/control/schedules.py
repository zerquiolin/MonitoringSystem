"""Central-clock cron occurrence; aware timezone conversion preserves DST semantics."""
from datetime import datetime
from zoneinfo import ZoneInfo
from croniter import croniter
def latest_due(schedule,timezone,now):
 return croniter(schedule,datetime.fromtimestamp(now,ZoneInfo(timezone))).get_prev(datetime).timestamp()
