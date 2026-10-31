"""Shift the AOI test results stored with the device wall clock read as UTC.

The AOI contract sends `testTime` without a UTC offset. Until this version
the value was stored as UTC, so the record and its defect lines sat one
device time zone delta ahead of the real UTC timestamp (8 hours for
Asia/Shanghai).

`create_date` always holds the real UTC insertion time, so the window below
only matches offset-less uploads and leaves every other test result alone.
The related test_time columns on the detail tables are stored copies and
have to be shifted with the header.
"""

import logging

_logger = logging.getLogger(__name__)

# Rows whose test_time sits exactly one device time zone delta ahead of the
# insertion time, with a slack for the upload latency.
DELTA_WINDOW = ('7:50', '8:10')

RELATED_TABLES = (
    'sn_wsd_aoi_defect_detail',
    'sn_wsd_mes_test_result_detail',
)


def migrate(cr, version):
    if not version:
        # fresh install: nothing was uploaded with the previous code
        return
    cr.execute(f"""
        CREATE TEMP TABLE tmp_aoi_tz_fix ON COMMIT DROP AS
        SELECT id
          FROM sn_wsd_mes_test_result
         WHERE source_system = 'AOI'
           AND test_time BETWEEN create_date + interval '{DELTA_WINDOW[0]}'
                              AND create_date + interval '{DELTA_WINDOW[1]}'
    """)
    cr.execute('SELECT count(*) FROM tmp_aoi_tz_fix')
    fixed = cr.fetchone()[0]
    if not fixed:
        _logger.info('device time zone fix: no AOI test result to shift')
        return

    cr.execute("""
        UPDATE sn_wsd_mes_test_result
           SET test_time = test_time - interval '8 hours'
         WHERE id IN (SELECT id FROM tmp_aoi_tz_fix)
    """)
    for table in RELATED_TABLES:
        cr.execute(f"""
            UPDATE {table}
               SET test_time = test_time - interval '8 hours'
             WHERE test_result_id IN (SELECT id FROM tmp_aoi_tz_fix)
        """)
    _logger.info(
        'device time zone fix: %s AOI test result(s) and their detail lines '
        'shifted to real UTC', fixed)
