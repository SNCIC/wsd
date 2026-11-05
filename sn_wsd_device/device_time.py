"""Time-zone handling shared by the shop-floor device endpoints.

Odoo stores a ``fields.Datetime`` as a naive UTC value and the web client
renders it in the user time zone (see ``odoo/orm/fields_temporal.py`` and
``addons/web/static/src/core/l10n/dates.js``). Devices push their own wall
clock, which usually carries no UTC offset, so the offset has to be applied
while parsing the payload. Reading such a value as UTC would make every
screen show the timestamp shifted by the whole time-zone delta (8 hours for
Asia/Shanghai).
"""

from datetime import datetime, timezone

import pytz

# Wall-clock time zone of the devices when a payload carries no offset.
DEVICE_TIMEZONE = 'Asia/Shanghai'


def parse_device_datetime(raw):
    """Convert a device ISO 8601 timestamp into a naive UTC datetime.

    A value carrying an offset (``+08:00`` or a ``Z`` suffix) is converted
    as is. A value without an offset is a device wall-clock time and is
    localized in :data:`DEVICE_TIMEZONE` first, so the database keeps real
    UTC and the client displays the time the device actually measured.

    :raises ValueError: when ``raw`` is not an ISO 8601 datetime.
    """
    text = str(raw).strip()
    if text.endswith(('Z', 'z')):
        # datetime.fromisoformat only accepts a numeric offset before 3.11
        text = text[:-1] + '+00:00'
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return (pytz.timezone(DEVICE_TIMEZONE)
            .localize(parsed, is_dst=False)
            .astimezone(pytz.utc)
            .replace(tzinfo=None))
