# -*- coding: utf-8 -*-
"""工作中心-设备关联的需求契约测试。

REQ-001 在工作中心的设备清单中添加设备并保存时，系统应当将该设备归入本工作中心的设备清单。
REQ-009 当用户在工作中心中选择的设备已属于其他工作中心时，系统应当阻止并提示该设备当前所属的工作中心。
REQ-010 工作中心设备清单中的设备应当按照顺序字段升序排列；顺序值由用户手工录入。
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWorkcenterEquipment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Equipment = cls.env['sn.wsd.device.equipment']
        cls.Line = cls.env['sn.wsd.workcenter.equipment']
        cls.Workcenter = cls.env['mrp.workcenter']
        cls.equipment = cls.Equipment.create(
            {'code': 'EQ-WC-T1', 'name': 'Placer M1'})
        cls.workcenter = cls.Workcenter.create({'name': 'WC-EQ-A'})

    def _create_line(self, workcenter, equipment, sequence=10):
        return self.Line.create({
            'workcenter_id': workcenter.id,
            'equipment_id': equipment.id,
            'sequence': sequence,
        })

    # REQ-001: 添加设备归入本工作中心
    def test_add_equipment_to_workcenter(self):
        line = self._create_line(self.workcenter, self.equipment)
        self.assertEqual(line.workcenter_id, self.workcenter)
        self.assertEqual(line.equipment_id, self.equipment)

    # REQ-001: 设备清单中可见
    def test_equipment_in_workcenter_list(self):
        self._create_line(self.workcenter, self.equipment)
        self.assertEqual(
            self.workcenter.sn_equipment_ids.mapped('equipment_id'),
            self.equipment)

    # REQ-009: 新增路径阻止重复归属
    def test_reject_equipment_already_on_other_workcenter(self):
        other = self.Workcenter.create({'name': 'WC-EQ-B'})
        self._create_line(self.workcenter, self.equipment)
        with self.assertRaises(ValidationError):
            self._create_line(other, self.equipment)

    # REQ-009: 修改路径阻止重复归属
    def test_reject_duplicate_on_write(self):
        other = self.Workcenter.create({'name': 'WC-EQ-B'})
        equipment2 = self.Equipment.create(
            {'code': 'EQ-WC-T2', 'name': 'Reflow'})
        line_a = self._create_line(self.workcenter, self.equipment)
        line_b = self._create_line(other, equipment2)
        with self.assertRaises(ValidationError):
            line_b.write({'equipment_id': self.equipment.id})
        self.assertEqual(line_b.equipment_id, equipment2)
        self.assertEqual(line_a.equipment_id, self.equipment)

    # REQ-009: 阻止提示包含该设备当前所属的工作中心名称
    def test_error_names_current_workcenter(self):
        other = self.Workcenter.create({'name': 'WC-EQ-B'})
        self._create_line(self.workcenter, self.equipment)
        with self.assertRaises(ValidationError) as err:
            self._create_line(other, self.equipment)
        self.assertIn('WC-EQ-A', str(err.exception))

    # REQ-010: 清单按手工录入的 sequence 升序排列
    def test_equipment_ordered_by_sequence(self):
        eq2 = self.Equipment.create({'code': 'EQ-WC-T2', 'name': 'Reflow'})
        eq3 = self.Equipment.create({'code': 'EQ-WC-T3', 'name': 'AOI'})
        self._create_line(self.workcenter, eq2, sequence=30)
        self._create_line(self.workcenter, self.equipment, sequence=10)
        self._create_line(self.workcenter, eq3, sequence=20)
        self.assertEqual(
            self.workcenter.sn_equipment_ids.mapped('sequence'), [10, 20, 30])

    # 默认行为: 移除清单行即解除关联
    def test_remove_equipment_unlinks(self):
        line = self._create_line(self.workcenter, self.equipment)
        line.unlink()
        self.assertFalse(self.workcenter.sn_equipment_ids)
