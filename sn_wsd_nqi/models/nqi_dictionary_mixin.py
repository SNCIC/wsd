"""Import upsert for the NQI dictionaries.

A workbook issued by the NQI side carries natural keys (code type +
code id, component code) but no external ids. A plain import would
create every row again and fail on the unique key. Resolving the
natural key to the existing record's external id lets the standard
import update that record instead; unknown keys are created as usual.
"""
from odoo import models


class NqiDictionaryMixin(models.AbstractModel):
    _name = 'sn.wsd.nqi.dictionary.mixin'
    _description = 'NQI Dictionary Import Upsert'

    # columns that identify a row of the dictionary
    _nqi_import_key = ()

    def _nqi_import_xmlid(self, record):
        """External id of an existing dictionary row, creating one when
        the row has none (a row born from a previous import): the id
        column of load() only understands external ids."""
        xmlid = record.get_external_id()[record.id]
        if xmlid:
            return xmlid
        Data = self.env['ir.model.data']
        module = self._module or '__import__'
        name = '%s_import_%s_%s' % (record._table, module, record.id)
        Data.create({
            'module': module,
            'name': name,
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        })
        return '%s.%s' % (module, name)

    def load(self, fields, data):
        fields = list(fields)
        data = [list(row) for row in data]
        key = list(self._nqi_import_key)
        if key and all(name in fields for name in key):
            if 'id' not in fields:
                fields = fields + ['id']
                data = [row + [''] for row in data]
            id_at = fields.index('id')
            key_at = [fields.index(name) for name in key]
            xml_ids = {}
            for row in data:
                values = [row[at] or False for at in key_at]
                # a row that names its own external id is left alone
                if row[id_at] or not all(values):
                    continue
                natural_key = tuple(values)
                if natural_key not in xml_ids:
                    existing = self.search(
                        [(name, '=', value)
                         for name, value in zip(key, values)], limit=1)
                    xml_ids[natural_key] = (
                        self._nqi_import_xmlid(existing) if existing else '')
                if xml_ids[natural_key]:
                    row[id_at] = xml_ids[natural_key]
        return super().load(fields, data)
