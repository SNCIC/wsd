# -*- coding: utf-8 -*-
"""Options of the "Import Materials from Kingdee" button.

The run itself belongs to ``product.template`` (``_kingdee_import_materials()``);
this transient model only collects what the run should do and reports what it did,
so the same entry point can be reused by a scheduled action later on.
"""

from odoo import fields, models


class SnWsdKingdeeMaterialImport(models.TransientModel):
    """Form behind the Kingdee menu entry that pulls materials into Odoo."""

    _name = "sn.wsd.kingdee.material.import"
    _description = "Import Kingdee Materials"

    filter_string = fields.Char(
        string="Kingdee Filter",
        help="Optional Kingdee FilterString, e.g. \"FDocumentStatus = 'C'\" to read the "
             "audited materials only. Empty reads every material.",
    )
    limit = fields.Integer(
        string="Maximum Materials",
        default=0,
        help="Highest number of materials read from Kingdee. 0 reads them all.",
    )
    include_disabled = fields.Boolean(
        string="Include Disabled Materials",
        help="Also import the materials disabled (FForbidStatus) in Kingdee. They are "
             "skipped by default. The product is never archived either way.",
    )
    update_existing = fields.Boolean(
        string="Update Linked Products",
        default=True,
        help="Refresh the Kingdee classification of the products already linked to a "
             "material. The product name is never overwritten.",
    )
    create_missing = fields.Boolean(
        string="Create Missing Products",
        default=True,
        help="Create the products of the Kingdee materials Odoo does not have yet.",
    )

    def action_preview(self):
        """Read the materials and report what a full import would do.

        Nothing is written: this is the step that tells how many products an
        import would create before any is created.
        """
        self.ensure_one()
        summary = self.env["product.template"]._kingdee_import_materials(
            filter_string=self.filter_string or "",
            limit=self.limit or 0,
            include_disabled=self.include_disabled,
            dry_run=True,
        )
        return self.env["product.template"]._kingdee_import_notification(summary, dry_run=True)

    def action_import(self):
        """Read the materials and report what was created, updated and skipped."""
        self.ensure_one()
        summary = self.env["product.template"]._kingdee_import_materials(
            filter_string=self.filter_string or "",
            limit=self.limit or 0,
            update_existing=self.update_existing,
            create_missing=self.create_missing,
            include_disabled=self.include_disabled,
        )
        return self.env["product.template"]._kingdee_import_notification(summary)
