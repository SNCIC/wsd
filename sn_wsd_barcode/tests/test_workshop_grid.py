"""Workshop grid entries and the removal of the legacy scan routes.

The station-pass screen and the rebuilt exception screen replaced the old
quality-issue flow (SN + defect code) and the orphan workshop scan route;
both must be gone for good (no degraded compatibility) and the grid must
expose the five entries with the right group visibility."""

import json

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestWorkshopGridLegacyRoutes(HttpCase):

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')

    def _post(self, path):
        return self.url_open(
            path,
            data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'id': 1,
                             'params': {}}),
            headers={'Content-Type': 'application/json'},
        )

    def test_01_legacy_routes_are_gone(self):
        for path in (
            '/sn_wsd_barcode/quality/resolve_exception_sn',
            '/sn_wsd_barcode/quality/report_exception',
            '/sn_wsd_barcode/process_workshop_scan',
        ):
            with mute_logger('odoo.http'):
                self.assertEqual(self._post(path).status_code, 404, path)

    def test_02_station_pass_entry_is_public(self):
        # "everyone" is expressed as the internal-user group, like the
        # exception entry: no Shop/SMT/Warehouse restriction may sneak in
        internal = self.env.ref('base.group_user')
        menu = self.env.ref('sn_wsd_barcode.menu_workshop_fn_station_pass')
        self.assertEqual(menu.group_ids, internal)
        self.assertEqual(menu.action.tag, 'sn_wsd_barcode_station_pass')
        exception_menu = self.env.ref('sn_wsd_barcode.menu_workshop_fn_exception')
        self.assertEqual(exception_menu.group_ids, internal)
