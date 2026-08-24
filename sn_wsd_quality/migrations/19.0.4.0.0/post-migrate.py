import logging

from odoo.tools import sql


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    if not sql.table_exists(cr, 'sn_wsd_serial_identity'):
        return
    # the quality lamp moved from the archive registry to the identity:
    # light it for identities with open issues
    cr.execute('''
        UPDATE sn_wsd_serial_identity i
           SET x_quality_hold_state = 'hold'
         WHERE EXISTS (
               SELECT 1 FROM sn_wsd_quality_issue q
                WHERE q.serial_identity_id = i.id
                  AND q.state NOT IN ('closed', 'scrapped'))
    ''')
    cr.execute('SELECT count(*) FROM sn_wsd_serial_identity WHERE x_quality_hold_state = %s', ['hold'])
    _logger.info('sn_wsd_quality 19.0.4.0.0: %s identities on quality hold',
                 cr.fetchone()[0])
