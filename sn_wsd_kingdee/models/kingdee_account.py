# -*- coding: utf-8 -*-
"""One row per Kingdee account (data center).

Why a model and not more system parameters: the WebAPI credentials identify **one
account**, and the migration run of December 2026 works against two of them (the
test account used to prove a document, the production account that receives it).
The parameters of the module are global, so a second account could only be reached
by editing them by hand and clearing the session cache - a switch nobody can audit.

A row carries the five credentials of the WebAPI login **and** the values this
account imposes on the documents: the organizations, the owner and keeper types,
the stock statuses and the default employee numbers. Those are account data, not
code: a field that is mandatory here is refused there, and guessing one is exactly
what ``docs/kingdee-接入SOP.md`` forbids.

A row without company is available to every company; a company bound to a row uses
it for all its calls. No row at all is the previous behaviour: the credentials are
read from the system parameters (Settings -> Kingdee), so an existing database keeps
working after the upgrade.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Owner and keeper type of a stock document whose goods belong to the organization
# itself. The other options of the account are a supplier and a customer, which this
# integration never books (MES goods belong to the company until they are shipped).
OWNER_TYPE_SELECTION = [
    ("BD_OwnerOrg", "Business Organization"),
    ("BD_Supplier", "Supplier"),
    ("BD_Customer", "Customer"),
]

KEEPER_TYPE_SELECTION = [
    ("BD_KeeperOrg", "Business Organization"),
    ("BD_Supplier", "Supplier"),
    ("BD_Customer", "Customer"),
]


class SnWsdKingdeeAccount(models.Model):
    """Credentials and account wide defaults of one Kingdee data center."""

    _name = "sn.wsd.kingdee.account"
    _description = "Kingdee Account"
    _order = "sequence, id"

    name = fields.Char(
        string="Account", required=True,
        help="Label of the data center, e.g. ZNDB Production or ZNDB Test.",
    )
    code = fields.Char(
        string="Code", required=True, index=True,
        help="Short code used in messages, e.g. ZNDB-PROD.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_test = fields.Boolean(
        string="Test Account",
        help="Marks the account used to prove a document before it reaches the "
             "production account. A test account is never used by the scheduled "
             "push.",
    )
    company_ids = fields.Many2many(
        "res.company", "sn_wsd_kingdee_account_company_rel",
        "account_id", "company_id", string="Companies",
        help="Companies whose calls go to this account. Empty means every company.",
    )
    note = fields.Text(string="Notes")

    # ------------------------------------------------------------------
    # Credentials (same five values the WebAPI login needs)
    # ------------------------------------------------------------------
    server_url = fields.Char(
        string="Server URL", required=True,
        help="Kingdee K/3 Cloud base URL, it must end with /k3cloud/.",
    )
    acct_id = fields.Char(string="Account ID", required=True)
    user_name = fields.Char(string="User Name", required=True)
    app_id = fields.Char(string="App ID", required=True)
    app_secret = fields.Char(
        string="App Secret", required=True,
        help="Stored unencrypted: keep this model restricted to administrators.",
    )
    lcid = fields.Integer(string="Locale ID", default=2052)
    org_num = fields.Integer(
        string="Organization Number", default=0,
        help="0 for an account that is not multi-organization.",
    )
    connect_timeout = fields.Integer(string="Connection Timeout (s)", default=120)
    request_timeout = fields.Integer(string="Request Timeout (s)", default=120)

    # ------------------------------------------------------------------
    # Organizations of the documents
    # ------------------------------------------------------------------
    create_org_number = fields.Char(
        string="Create Organization", required=True,
        help="Organization number used as the create/use organization of a record "
             "and as the business organization of the stock documents (FStockOrgId, "
             "FPrdOrgId, FSaleOrgId, FPurchaseOrgId).",
    )
    use_org_number = fields.Char(
        string="Use Organization",
        help="Defaults to the create organization.",
    )
    send_create_org_id = fields.Boolean(
        string="Send CreateOrgId",
        help="Injects CreateOrgId in the parameters of Save. Off by default: a bill "
             "carries its own organization fields, and an unknown parameter is "
             "refused by the account.",
    )

    # ------------------------------------------------------------------
    # Account values of the documents
    # ------------------------------------------------------------------
    owner_type = fields.Selection(
        OWNER_TYPE_SELECTION, string="Owner Type", default="BD_OwnerOrg", required=True,
    )
    keeper_type = fields.Selection(
        KEEPER_TYPE_SELECTION, string="Keeper Type", default="BD_KeeperOrg", required=True,
    )
    stock_status_number = fields.Char(
        string="Available Stock Status", default="KCZT01_SYS", required=True,
        help="BD_StockStatus written on the lines of a stock document in good "
             "condition (KCZT01_SYS is 可用 in this account).",
    )
    quarantine_stock_status_number = fields.Char(
        string="Inspection Stock Status", default="KCZT02_SYS",
        help="Stock status of the goods waiting for a quality decision (KCZT02_SYS "
             "is 待检).",
    )
    frozen_stock_status_number = fields.Char(
        string="Frozen Stock Status", default="KCZT03_SYS",
        help="Stock status of a batch the quality department froze (KCZT03_SYS is "
             "冻结).",
    )
    default_currency_number = fields.Char(
        string="Default Currency", default="PRE001",
        help="Currency written on a document whose currency carries no Kingdee "
             "number (PRE001 is 人民币 in this account).",
    )
    default_employee_number = fields.Char(
        string="Default Employee",
        help="BD_NEWSTAFF number used for the acceptance and picker fields when the "
             "document names no employee.",
    )
    default_stocker_number = fields.Char(
        string="Default Warehouse Keeper",
        help="BD_WAREHOUSEWORKERS number used for the keeper field when the document "
             "names no employee.",
    )
    default_department_number = fields.Char(
        string="Default Department",
        help="BD_Department number used for the department fields when the document "
             "carries no department.",
    )
    default_salesman_number = fields.Char(
        string="Default Salesman",
        help="BD_Saler number required by a sales order when the Odoo user has no "
             "salesman linked.",
    )
    default_sales_dept_number = fields.Char(
        string="Default Sales Department",
        help="BD_Department number required by a delivery when the order names no "
             "sales department.",
    )
    auto_push_bills = fields.Boolean(
        string="Automatic Push",
        default=True,
        help="Push a document as soon as it is done, instead of waiting for the "
             "scheduled action. Each document type has its own switch.",
    )

    _code_uniq = models.Constraint("UNIQUE(code)", "The account code must be unique.")

    @api.constrains("app_secret", "acct_id")
    def _check_credentials(self):
        for account in self:
            if account.app_secret and len(account.app_secret) < 16:
                raise ValidationError(_(
                    "The app secret of %s looks too short to be a Kingdee secret."
                ) % account.name)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    @api.model
    def _for_company(self, company):
        """Account the calls of ``company`` go to (empty when none is configured)."""
        return self.search([
            ("active", "=", True),
            "|", ("company_ids", "=", False), ("company_ids", "in", company.ids),
        ], limit=1)

    @api.model
    def _production(self):
        """Account used by the scheduled push: the active account that is not a test."""
        return self.search([("active", "=", True), ("is_test", "=", False)], limit=1)

    def _to_config(self):
        """Configuration mapping read by ``sn.wsd.kingdee.client``."""
        self.ensure_one()
        return {
            "server_url": (self.server_url or "").strip(),
            "acct_id": (self.acct_id or "").strip(),
            "user_name": (self.user_name or "").strip(),
            "app_id": (self.app_id or "").strip(),
            "app_secret": (self.app_secret or "").strip(),
            "lcid": self.lcid or 2052,
            "org_num": self.org_num or 0,
            "connect_timeout": self.connect_timeout or 120,
            "request_timeout": self.request_timeout or 120,
        }

    def _stock_status_for(self, lot=None):
        """Stock status of a batch: available, waiting for a decision or frozen.

        The quality hold of the batch is what the account records in its stock
        status, so a blocked batch leaves the available stock instead of being
        counted twice.
        """
        self.ensure_one()
        hold = getattr(lot, "sn_hold_state", False) if lot else False
        if hold == "blocked":
            return self.frozen_stock_status_number or "KCZT03_SYS"
        if hold == "sealed":
            return self.quarantine_stock_status_number or "KCZT02_SYS"
        return self.stock_status_number or "KCZT01_SYS"

    def _org_number(self, kind="create"):
        self.ensure_one()
        if kind == "use":
            return (self.use_org_number or self.create_org_number or "").strip()
        return (self.create_org_number or "").strip()

    @api.depends("code", "name")
    def _compute_display_name(self):
        for account in self:
            account.display_name = "%s (%s)" % (account.code, account.name)
