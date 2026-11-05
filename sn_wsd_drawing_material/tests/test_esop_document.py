import base64

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEsopDocument(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def _get_or_create(model, code_key, code, name, **kw):
            existing = cls.env[model].search([(code_key, '=', code)], limit=1)
            return existing or cls.env[model].create({code_key: code, 'name': name, **kw})

        cls.operation = _get_or_create(
            'sn.wsd.operation', 'name', 'ESOP Test Operation',
            'ESOP Test Operation')
        cls.other_operation = _get_or_create(
            'sn.wsd.operation', 'name', 'ESOP Test Welding',
            'ESOP Test Welding')
        cls.drawing_product = cls.env['product.product'].create({
            'name': 'ESOP Test Board',
            'default_code': 'ESOP-DWG-01',
        })
        # acknowledgements record the logged-in user's employee
        if not cls.env.user.employee_id:
            cls.env['hr.employee'].create({
                'name': 'ESOP Test Employee',
                'user_id': cls.env.user.id,
            })

    def _create_document(self, **kw):
        values = {
            'x_drawing_no': 'ESOP-DWG-01',
            'operation_id': self.operation.id,
            'x_side': 'top',
            'doc_type': 'instruction',
            'name': 'SOP for placement',
            'file': base64.b64encode(b'%PDF-1.4 test'),
            'file_name': 'sop.pdf',
        }
        values.update(kw)
        return self.env['sn.wsd.esop.document'].create(values)

    def test_create_defaults(self):
        document = self._create_document()
        self.assertEqual(document.state, 'active')
        self.assertEqual(document.version, 'V1')
        self.assertIn('ESOP-DWG-01', document.display_name)
        self.assertIn('ESOP Test Operation', document.display_name)

    def test_product_info_derived(self):
        document = self._create_document()
        self.assertEqual(document.product_id, self.drawing_product)
        self.assertEqual(document.product_name, 'ESOP Test Board')

        unknown = self._create_document(
            x_drawing_no='ESOP-DWG-UNKNOWN', doc_type='drawing')
        self.assertFalse(unknown.product_id)
        self.assertFalse(unknown.product_name)

    def test_reversion_archives_previous(self):
        first = self._create_document()
        second = self._create_document(name='SOP for placement, rev 2')
        self.assertEqual(first.state, 'archived')
        self.assertTrue(first.archived_date)
        self.assertTrue(first.archived_uid)
        self.assertEqual(first.version, 'V1')
        self.assertEqual(second.state, 'active')
        self.assertEqual(second.version, 'V2')

        third = self._create_document(name='SOP for placement, rev 3')
        self.assertEqual(third.version, 'V3')

    def test_version_sequenced_even_when_passed(self):
        # the create form submits the field default V1 explicitly; the
        # server must still sequence re-versions
        self._create_document()
        second = self._create_document(
            name='SOP for placement, rev 2', version='V1')
        self.assertEqual(second.version, 'V2')

    def test_doc_types_coexist(self):
        instruction = self._create_document()
        drawing = self._create_document(doc_type='drawing')
        inspection = self._create_document(doc_type='inspection')
        self.assertEqual(
            (instruction.state, drawing.state, inspection.state),
            ('active', 'active', 'active'))

    def test_dimensions_coexist(self):
        top = self._create_document()
        bottom = self._create_document(x_side='bottom')
        other_op = self._create_document(
            operation_id=self.other_operation.id)
        self.assertEqual(len({top.id, bottom.id, other_op.id}), 3)

    def test_active_unique_db_guard(self):
        first = self._create_document()
        self._create_document(name='SOP for placement, rev 2')
        # reviving the archived row bypasses create()'s auto-archive
        with self.assertRaises(IntegrityError):
            first.write({'state': 'active'})
            self.env.flush_all()

    def test_screen_search(self):
        self._create_document()
        self._create_document(doc_type='drawing')
        data = self.env['sn.wsd.esop.document'].esop_screen_data('ESOP-DWG')
        self.assertEqual(len(data['docs']), 2)
        doc = data['docs'][0]
        self.assertEqual(doc['drawing'], 'ESOP-DWG-01')
        self.assertIn('/web/content', doc['url'])
        self.assertEqual(doc['version'], 'V1')

    def test_screen_search_no_match(self):
        self._create_document()
        data = self.env['sn.wsd.esop.document'].esop_screen_data('NOPE')
        self.assertEqual(data['docs'], [])
        self.assertEqual(data['cards'], [])

    def test_screen_landing_cards_follow_live_orders(self):
        self._create_document()
        data = self.env['sn.wsd.esop.document'].esop_screen_data('')
        # the dev database carries live orders: compare against the same
        # domain instead of assuming an empty shop floor
        live = self.env['sn.wsd.mes.order'].search([
            ('company_id', '=', self.env.company.id),
            ('state', '=', 'in_progress'),
        ])
        expected = {
            order.product_id.default_code for order in live
            if order.product_id.default_code}
        self.assertEqual(
            {card['drawing'] for card in data['cards']}, expected)
        for card in data['cards']:
            self.assertIn('unacked', card)
        self.assertTrue(data['can_ack'])

    def test_ack_flow(self):
        document = self._create_document()
        Acknowledge = self.env['sn.wsd.esop.acknowledge']
        document.esop_acknowledge()

        acks = Acknowledge.search([('document_id', '=', document.id)])
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks.employee_id, self.env.user.employee_id)
        self.assertEqual(acks.version, 'V1')

        # acknowledging twice does not duplicate
        document.esop_acknowledge()
        self.assertEqual(
            Acknowledge.search_count([('document_id', '=', document.id)]), 1)

        # the screen no longer flags the acknowledged version
        data = self.env['sn.wsd.esop.document'].esop_screen_data('ESOP-DWG')
        self.assertFalse([doc for doc in data['docs'] if doc['unacked']])

        # a re-versioned document needs acknowledgement again
        second = self._create_document(name='SOP for placement, rev 2')
        data = self.env['sn.wsd.esop.document'].esop_screen_data('ESOP-DWG')
        active_doc = next(
            doc for doc in data['docs'] if doc['id'] == second.id)
        self.assertTrue(active_doc['unacked'])

    def test_ack_unique_db_guard(self):
        document = self._create_document()
        Acknowledge = self.env['sn.wsd.esop.acknowledge']
        values = {
            'employee_id': self.env.user.employee_id.id,
            'document_id': document.id,
            'version': 'V1',
        }
        Acknowledge.create(values)
        with self.assertRaises(IntegrityError):
            Acknowledge.create(values)
