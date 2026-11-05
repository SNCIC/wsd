"""Shift the soldering records stored with the device wall clock read as UTC.

Devices push their own wall-clock time without a UTC offset. Until this
version the payload was stored as UTC, so every such value sits one device
time zone delta ahead of the real UTC timestamp (8 hours for Asia/Shanghai)
and the client rendered it 8 hours late.

`create_date` always holds the real UTC insertion time, so the detection
window below only matches the offset-less uploads (old rows are ~8 hours
ahead of their insertion, new rows are within seconds of it). The table is
empty on a fresh database, which makes the migration a no-op there.
"""

import logging

_logger = logging.getLogger(__name__)

TABLES = ('sn_wsd_device_reflow_record', 'sn_wsd_device_wave_record')

# Rows whose collect_time sits exactly one device time zone delta ahead of
# the insertion time, with a slack for the upload latency.
DELTA_WINDOW = ('7:50', '8:10')


def migrate(cr, version):
    if not version:
        # fresh install: nothing was collected with the previous code
        return
    for table in TABLES:
        cr.execute(f"""
            UPDATE {table}
               SET collect_time = collect_time - interval '8 hours'
             WHERE collect_time BETWEEN create_date + interval '{DELTA_WINDOW[0]}'
                                    AND create_date + interval '{DELTA_WINDOW[1]}'
        """)
        _logger.info(
            'device time zone fix: %s row(s) of %s shifted to real UTC',
            cr.rowcount, table)
