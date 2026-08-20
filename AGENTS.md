# AGENTS.md — wsd 开发规范

本文件是 ZCode（以及所有贡献者）在本仓库开发 `sn_wsd_*` / `muk_web_*` 模块时必须遵守的规则。

## 注意
**1.注意多公司，在处理任何业务时，首先考虑到多公司**
**2.不允许考虑降级处理，现在是开发阶段，如果有问题处理老旧数据，也不能为了老旧数据给逻辑变更**

## 仓库与运行环境

- 本目录（`wsd/`）是独立 git 仓库（github.com/SNCIC/wsd），作为 Odoo 19 的 addons 路径之一挂载。
- 运行环境：Odoo 19，Python 3.12（`D:\ProgramDatas\Anaconda\envs\odoo19\python.exe`）。
- 两套并行环境，共用同一 PostgreSQL（localhost:5432，用户 `odoo19`）：

| | 企业版（现状） | 社区版（开发目标） |
|---|---|---|
| 源码 | `D:\odoo19e20250921-f`（企业模块混在 `odoo\addons` 内） | `D:\odoo19-community`（junction/hardlink 镜像，仅 659 个社区模块） |
| conf | `D:\wsd\odoo.local.conf` | `D:\wsd\odoo.community.conf` |
| 端口 | 8069 | 8070 |
| 数据库 | `mes` | `mes_community`（28 个 wsd/muk 模块全部可装，0 企业模块） |
| 日志 | `D:\wsd\odoo-server.log` | `D:\wsd\odoo-community-server.log` |

- **企业版启动** `D:\ProgramDatas\Anaconda\envs\odoo19\python.exe D:\odoo19e20250921-f\odoo-bin -c D:\wsd\odoo.local.conf -d mes`
- **社区版启动** `D:\ProgramDatas\Anaconda\envs\odoo19\python.exe D:\odoo19-community\odoo-bin -c D:\wsd\odoo.community.conf`（访问 http://localhost:8070）
- 社区版升级模块把 odoo-bin 路径换成社区版并加 `-u <MOD> --stop-after-init`（库用 `-d mes_community`）。

### 社区版环境要点（务必遵守）

0. **开发只在社区版进行**：日常开发、模块升级（`-u`）、测试一律走社区版（http://localhost:8070 / `mes_community`）；企业版（8069 / `mes`）无需启动、升级或维护，除非用户明确要求。
1. **必须用 `D:\odoo19-community\odoo-bin` 启动社区版**：Odoo 会把运行包自身的 `odoo\addons` 无条件加入模块搜索路径。用企业版源码的 odoo-bin 启动时，即使 conf 里写了社区 addons 路径，`web_enterprise` 等企业模块仍会被自动装上（auto_install）。
2. `D:\odoo19-community` 是由 `D:\odoo19e20250921-f\odoo` 按 manifest `license`（OEEL-1/OPL-1 = 企业版）过滤生成的 junction/hardlink 镜像，**不要在里面改代码**（改了等于改企业版源码）；原企业版源码目录保持不动，8069 实例不受影响。
3. 社区版开发时**不要新增对企业版模块的依赖**：`mrp.workorder`、`mrp.workcenter.productivity` 模型和工单视图在 Odoo 19 社区版 `mrp` 模块里就有，可直接用；甘特图用自带的 `sn_wsd_gantt`（已移植企业 `web_gantt` 的完整 JS），**不要**依赖 `web_gantt`/`web_enterprise`。
4. `sn_wsd_barcode` 的路由路径刻意避开企业版 `stock_barcode` 占用的 `barcode`/`barcode-operations` 路径，保持两版兼容，改动时勿破坏。

## 核心原则：源码全英文，翻译靠 .po，数据库不存中文

### 必须用英文的位置（用户可见字符串，出现中文即算违规）

1. **Python 字段定义**
   - `fields.Char(string='Device SN')` ✅ ／ `string='设备SN'` ❌
   - `help='...'`、`compute` 字段的说明文本同样英文。
2. **Selection 字段** —— key 是稳定的英文代码（存进 DB 永不改），第二个元素是英文标签，再由 `.po` 翻译：
   ```python
   # ✅
   state = fields.Selection(
       selection=[('draft', 'Draft'), ('confirmed', 'Confirmed'), ('done', 'Done')],
       string='State', default='draft',
   )
   # ❌ selection=[('draft', '草稿'), ...]   —— 标签写中文会被存进库
   ```
3. **Python 用户提示** —— `UserError`、`ValidationError`、所有 `_('...')` 包裹的串必须英文。
4. **XML 视图** —— `<field string="...">`、`<page string="...">`、`<button string="...">`、`<group>`、`<notebook>` 等所有 `string` 属性英文。
5. **菜单** —— `<menuitem name="Shop Floor"/>` ✅ ／ `name="车间"` ❌。
6. **Data / 记录规则 / 模板** —— `ir.rule` 的 name、邮件模板 subject/body、报表标题等英文。
7. **JS / OWL / QWeb 模板** —— 前端显示文本英文，走 `_t()` / `_()` 翻译。

### 允许中文的位置

- `i18n/zh_CN.po`（**唯一**的中文存放点）。
- **代码注释 / docstring**（非用户可见，允许中文）。
- commit message、PR 描述、本文档等元信息。

### 翻译流程

1. 正确做法：**源码里一律写英文**，中文只出现在 `i18n/zh_CN.po`。运行时 Odoo 按 `zh_CN` locale 用 `.po` 把英文替换成中文显示。

> 注：仓库内少数遗留文件（如部分 `sn_wsd_maintenance`/`sn_wsd_mrp` 的 `string='设备…'`、`menu_views.xml` 的 `name="车间"`）违反了本规则。新写或改动代码时一律按本规则执行，顺手修到的可一并改正。

## 开发闭环：升级 → 重启 → 测试（社区版）

每完成一个任务（加字段 / 改视图 / 改逻辑 / 改 `.po`），按需走这个闭环。

> `odoo.community.conf` 开了 `dev_mode = reload`：**纯 Python 逻辑**改动会被运行中的服务器自动重载，无需重启；但**字段结构、selection、视图、data、security、manifest、`.po`、JS** 的改动必须升级模块（JS 还需重建 asset：升级模块即可，或以 `--dev=assets` 启动）。

设当前模块名为 `MOD`（例如 `sn_wsd_workorder`），替换下面命令里的模块名即可。

### 1. 停服 → 升级模块（同时重载翻译）→ 重启

```bash
# 停服后执行升级（--stop-after-init 升级完即退出）：
D:/ProgramDatas/Anaconda/envs/odoo19/python.exe D:/odoo19-community/odoo-bin -c D:/wsd/odoo.community.conf -d mes_community -u sn_wsd_workorder --stop-after-init

# 重启社区版：
powershell -Command "Start-Process -FilePath 'D:\ProgramDatas\Anaconda\envs\odoo19\python.exe' -ArgumentList 'D:\odoo19-community\odoo-bin','-c','D:\wsd\odoo.community.conf' -WindowStyle Hidden -WorkingDirectory 'D:\wsd'"
```

- `-u <MOD>` 升级指定模块（多个用逗号）；`--stop-after-init` 让它升级完即退出。
- 新增了 `.po` 条目时，这步会把 zh_CN 翻译刷进库。

## 目录约定（沿用现有模块）

```
sn_wsd_xxx/
├── __init__.py
├── __manifest__.py
├── models/            # 业务模型
├── wizard/            # 向导 (model + view)
├── views/             # 视图 xml
├── security/          # ir.model.access.csv + groups/rules xml
├── data/              # 序列、配置参数、初始数据
├── tests/             # 测试
├── i18n/zh_CN.po      # 唯一的中文存放点
└── static/            # 前端资源 (js/scss/xml)
```

## 可复用组件：x2many 多选批量添加（`sn_wsd_x2many_multi_add`）

业务里常有"一个 One2many 列表，想一次从某模型挑多条记录批量加进来"的需求（如班组成员一次挑多个员工、工艺路线一次挑多道工序）。`sn_wsd_mrp` 已内置通用 OWL widget `sn_wsd_x2many_multi_add`，任意 One2many 都可复用。

### 用法

```xml
<field name="member_ids" widget="sn_wsd_x2many_multi_add"
       options="{'multi_add_model': 'hr.employee',          <!-- 数据源模型 -->
                 'multi_add_field': 'employee_id',          <!-- 目标行上指向源模型的 m2o 字段 -->
                 'multi_add_domain': '[("company_id", "=", company_id)]'}"/>
```

- `multi_add_model`：要挑的源模型。
- `multi_add_field`：目标行模型上指向源模型的 m2o 字段。建行时用 `default_<field>` 触发其 onchange，自动填充关联字段（如成员的工号、绩效比均分）。
- `multi_add_domain`（可选）：过滤源记录，可引用父记录字段。

> XML 里 `options` 的字符串值含双引号要用 `&quot;` 转义，否则破坏属性解析。

### ⚠️ 改动此组件务必遵守（踩过的坑）

1. **`extractProps` 不能用箭头函数的 `...arguments`**：箭头函数没有自己的 `arguments`，会取到外层（模块包装）的参数，导致基类 `x2ManyField.extractProps` 拿不到 `fieldInfo`、读 `attrs['add-label']` 崩溃。必须显式传参：`x2ManyField.extractProps(fieldInfo, dynamicInfo)`。
2. **客户端新建的行是虚拟草稿，失焦即丢**：`addNewRecord` 建出的行 `canBeAbandoned=true`，一旦点进去编辑、再点别处，可编辑列表的 `leaveEditMode(force)` 会把它丢弃（`_abandonRecords`，见 `addons/web/static/src/model/relational_model/static_list.js`）。根治办法：建完行后**立即 `await this.props.record.save()`**，让新行落库成真实记录（`canBeAbandoned=false`）。这也是 stock 走 `forceSave`+服务端的原因——不存在"纯前端建行又不丢弃"的两全法；若不想自动存父记录，就只能改走服务端创建（`orm.call` + reload）。
3. **循环建行用 `mode: "readonly"`**：默认 `mode:"edit"` 会让每行进编辑态、堆叠成多个 editedRecord。传 `mode:"readonly"` 避免堆叠；onchange 仍会触发（`_loadNewRecord` 在设 mode 之前跑，关联字段照常自动填）。
4. **option 域求值**：`new Domain(options.multi_add_domain || "[]").toList(record.evalContext)`——`Domain.toList(context)` 会解析 Python 域串并求值字段引用（与 `getFieldDomain` 同机制）。
5. **纯 JS 改动也要重建 asset**：`odoo.local.conf` 的 `dev_mode = reload` 不覆盖前端资源包；改 JS 后用 `--dev=assets` 启动（请求时重建包）或升级模块（`-u`）。



以下内容仅适用于odoo19版本，如果项目是odoo其他版本，参考对应版本源代码语法规范。

无论对odoo哪个版本进行拓展开发，都必须先学习分析拓展功能的官方相关源代码，再进行开发。自定义模块不需要写测试文件，新模块完成后自动安装让用户在系统中测试，已有模块更新后自动升级让用户在系统中测试。让用户测试时告诉用户如何测试，列出简短的操作步骤。

对于新增加的需要翻译的内容，先学习官方翻译文件规范，比如官方导出格式中的 #. module:、模型字段/Selection/Help 的 #: 来源引用，再添加到翻译文件，不要修改已有的翻译。

如果要进行升级操作，使用项目虚拟环境按照停服、升级、重启服务的方式。如果我需要同步升级到远程服务器，我会告诉你同步升级到哪个服务器，你从C:\Users\96364.ssh获取服务器信息。

```
# Odoo 19 AI Development Code Guidelines & Behavior Profiles

This document serves as the absolute system instructions and highest-priority ruleset for AI Agents generating, refactoring, or reviewing code for Odoo 19 custom modules. 

---

## 🤖 [AI Behavior Core Directive]
When writing Odoo 19 code, ALWAYS enforce the newer APIs, strict type safety, and the updated visual layer syntax. NEVER mixed or fallback to Odoo 16/17/18 legacy patterns (such as `attrs`, `states`, or `_sql_constraints`). Treat violations as syntax errors.

---

## 1. Python Models & Business Logic

### 1.1 Module Structure & Scaffolding
AI must maintain standard compliance for every newly created module:
```text
your_module/
├── __manifest__.py        # Must declare dependencies strictly
├── __init__.py            # Imports 'models', 'controllers', 'wizard' etc.
├── data/                  # XML configuration data (noupdate management)
├── models/
│   ├── __init__.py        # Explicitly import all python files
│   └── your_model.py
├── security/
│   ├── ir.model.access.csv
│   └── security_groups.xml
├── static/
│   ├── description/
│   │   └── index.html
│   └── src/               # OWL/JS/SCSS assets registration
└── views/
    └── your_views.xml     # <list> views instead of <tree>
```

### 1.2 Naming Conventions

* **Model Prefix:** `<span>sn.<name></span>` (e.g., `<span>sn.order.history</span>`).
* **Field Names:** Strictly `<span>snake_case</span>` (e.g., `<span>partner_id</span>`, `<span>is_expired</span>`).
* **Constants:** Strictly `<span>UPPERCASE</span>` inside python files (e.g., `<span>MAX_RETRY_COUNT = 5</span>`).
* **Imports:** Standard top-level import template:

```
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
```

### 1.3 Constraints API (Odoo 19 Pattern)

* **DEPRECATED:** `<span>_sql_constraints = [...]</span>` and legacy `<span>_constraints</span>`.
* **NEW STANDARD:** Use `<span>models.Constraint</span>` directly as a class attribute for DB-level checks, or `<span>@api.constrains</span>` for python business validation.

```
# 正确写法 (Right)
class SnBusinessDocument(models.Model):
    _name = 'sn.business.document'
    _description = 'Business Document'

    name = fields.Char(string="Code", required=True)
    percentage = fields.Integer(string="Percentage", default=0)

    # Odoo 19 DB-level Constraint API
    _check_percentage = models.Constraint(
        'CHECK(percentage >= 0 AND percentage <= 100)',
        'The percentage must be between 0 and 100.'
    )

    # Python Level Validation
    @api.constrains('name')
    def _check_unique_name(self):
        for record in self:
            domain = [('name', '=', record.name), ('id', '!=', record.id)]
            if self.search_count(domain) > 0:
                raise ValidationError(_("The document code '%s' must be unique!", record.name))
```

### 1.4 Default Values & Computed Fields

* Never override `<span>create()</span>` or `<span>write()</span>` solely to inject default values or compute field logic.
* Use `<span>default=</span>`, `<span>compute=</span>`, `<span>store=True</span>`, and `<span>@api.depends()</span>`.

```
# 正确写法 (Right)
value = fields.Float(string="Value")
tax = fields.Float(string="Tax", compute="_compute_tax", store=True)

@api.depends('value')
def _compute_tax(self):
    for record in self:
        record.tax = record.value * 0.13
```

### 1.5 CRUD Operations & Multi-Create Batching

* AI must optimize performance via `<span>@api.model_create_multi</span>`.
* Always forward calls to `<span>super()</span>` with correct arguments. Do not cause infinite recursion loops.

```
# 正确写法 (Right)
@api.model_create_multi
def create(self, vals_list):
    # Perform pre-creation enhancements safely on batch dictionaries
    for vals in vals_list:
        if 'name' not in vals or vals['name'] == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('sn.business.document') or '/'
    return super(SnBusinessDocument, self).create(vals_list)

def write(self, vals):
    # Only process mutated fields if specific business logic is required
    res = super(SnBusinessDocument, self).write(vals)
    return res
```

### 1.6 Multi-Company Compliance

* Enforce strict multi-company separation.
* Set `<span>_check_company_auto = True</span>`.
* Define relational fields pointing to company with `<span>company_id</span>`.

```
class SnOrder(models.Model):
    _name = 'sn.order'
    _check_company_auto = True

    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True, 
        default=lambda self: self.env.company
    )
    partner_id = fields.Many2one(
        'res.partner', 
        string='Customer', 
        check_company=True  # Automatically restricts selection to partner's company
    )
```

### 1.7 Business Auditing & Chatter Integration

* Critical models should inherit from `<span>mail.thread</span>` and `<span>mail.activity.mixin</span>` for logging.
* Track field changes by adding `<span>tracking=True</span>`. Use a secondary One2many historical snapshot model for complex business audits if necessary.

---

## XML Views & Data Files

### 2.1 Critical Upgrades: List Views & Attrs Deprecation

* **TAG TRANSITION:** `<span><tree></span>` is replaced by `<span><list></span>`. DO NOT generate `<span><tree>...</tree></span>` layout components.
* **ATTRS DEPRECATION:** Conditional visibility/read-only/required state must be declared inside inline attributes: `<span>invisible="..."</span>`, `<span>readonly="..."</span>`, `<span>required="..."</span>`.

#### Mapping Table for View Expressions:


| **Old Syntax (Odoo < 17)**                                      | **New Syntax (Odoo 19)**                                  |
| :-------------------------------------------------------------- | :-------------------------------------------------------- |
| `<span><tree></span>`                                           | `<span><list></span>`                                     |
| `<span>attrs="{'invisible': [('state', '=', 'draft')]}"</span>` | `<span>invisible="state == 'draft'"</span>`               |
| `<span>attrs="{'readonly': [('is_locked', '=', True)]}"</span>` | `<span>readonly="is_locked"</span>`                       |
| `<span>states="draft,sent"</span>`                              | `<span>invisible="state not in ['draft', 'sent']"</span>` |

### 2.2 Form View Architecture

* Inject status bars inside `<span><header></span>`.
* Append `<span><chatter/></span>` directly after the sheet component for clear layout binding.

```
<record id="view_sn_business_document_form" model="ir.ui.view">
    <field name="name">sn.business.document.form</field>
    <field name="model">sn.business.document</field>
    <field name="arch" type="xml">
        <form>
            <header>
                <field name="state" widget="statusbar" statusbar_visible="draft,posted,done"/>
            </header>
            <sheet>
                <div class="oe_title">
                    <h1><field name="name" readonly="1"/></h1>
                </div>
                <group>
                    <group>
                        <field name="partner_id"/>
                    </group>
                    <group>
                        <field name="company_id" invisible="1"/>
                        <field name="percentage" readonly="state == 'done'"/>
                    </group>
                </group>
            </sheet>
            <chatter/>
        </form>
    </field>
</record>
```

### 2.3 Kanban Views (OWL Structure compliance)

* **CRITICAL:** Every Kanban card template MUST map inside `<span><t t-name="card"></span>`.
* Legacy layout `<span><div class="oe_kanban_global_click"></span>` or `<span><t t-name="kanban-box"></span>` will crash the template engine throwing *"Missing 'card' template"* errors.

```
<record id="view_sn_business_document_kanban" model="ir.ui.view">
    <field name="name">sn.business.document.kanban</field>
    <field name="model">sn.business.document</field>
    <field name="arch" type="xml">
        <kanban default_group_by="state">
            <templates>
                <t t-name="card">
                    <div class="oe_kanban_global_click d-flex flex-column">
                        <div class="fw-bold fs-5">
                            <field name="name"/>
                        </div>
                        <div class="text-muted">
                            <field name="partner_id"/>
                        </div>
                    </div>
                </t>
            </templates>
        </kanban>
    </field>
</record>
```

### 2.4 Search Views

* Specify grouping operations using standard named `<span><group></span>` filters.
* **ANTI-PATTERN:** Never emit `<span><group expand="0" string="Group By"></span>`. The attribute `<span>expand="0"</span>` is strictly deprecated.

---

## Security & Access Control

### 3.1 Module Categorization & Group Hierarchies

* Define access category components using `<span>ir.module.category</span>`.
* Assign rights via `<span>res.groups</span>`. **Do not directly force** `<span>category_id</span>` allocations on raw single user profiles. Use `<span>Command</span>` abstractions to manage implied dependencies.

### 3.2 Secure Command API Conversions

When initializing XML relational records or groups, use `<span>Command</span>` helpers rather than legacy tuple structures:

* Instead of `<span>(4, id, 0)</span>` \$\\rightarrow\$ use `<span>Command.link(id)</span>`
* Instead of `<span>(5, 0, 0)</span>` \$\\rightarrow\$ use `<span>Command.clear()</span>`
* Instead of `<span>(2, id, 0)</span>` \$\\rightarrow\$ use `<span>Command.delete(id)</span>`

```
<record id="group_sn_manager" model="res.groups">
    <field name="name">Manager</field>
    <field name="category_id" ref="module_category_sn_management"/>
    <field name="implied_ids" eval="[Command.link(ref('base.group_user'))]"/>
</record>
```

### 3.3 Security CSV Boundaries (`<span>ir.model.access.csv</span>`)

* Every defined custom business model must contain an entry row mapping to explicit groups.
* Public or unrestricted global permission layers are strictly forbidden.
* Audit or version logs models must remain read-only for standard operational roles (`<span>1,0,0,0</span>`).

---

## Frontend, Assets & UI/UX Responsive Design

### 4.1 Asset Bundles (Odoo 19 Manifest)

* Do not include script or style sheets randomly inside XML definitions.
* Register all static extensions (`<span>SCSS</span>`/`<span>JS</span>`) via the `<span>assets</span>` dictionary key inside `<span>__manifest__.py</span>`.

```
# __manifest__.py asset registration
'assets': {
    'web.assets_backend': [
        'your_module/static/src/scss/custom_responsive.scss',
        'your_module/static/src/js/components/*.js',
    ],
},
```

### 4.2 Responsive CSS/SCSS Wrappers

* Scope custom UI enhancements explicitly. Use the dynamic class layout scope naming standard: `<span>.o_<module_name>_kanban</span>`.
* Leverage standard Bootstrap breakpoints (`<span>@include media-breakpoint-down(md)</span>`) to handle multi-device rendering optimizations seamlessly.

### 4.3 Element Sizing & Accessibility (Mobile UX)

* Buttons must deploy standard Bootstrap utility definitions (`<span>btn-primary</span>`, `<span>btn-secondary</span>`, `<span>oe_stat_button</span>`).
* Touch targets must support clear interactivity margins (minimum `<span>44px</span>` physical touch boundaries).
* Avoid complex multi-layered `<span><group></span>` sub-nesting layouts on forms. Leverage `<span><notebook></span>` structural groupings instead to maintain visibility stream continuity across devices.

---

## Data Migration, Testing & Versioning

### 5.1 Noupdate Directives Management

* Infrastructure components, sequences, system configurations, and baseline transactional workflows state steps must remain locked against automatic upgrade overrides using `<span>noupdate="1"</span>`.

```
<odoo>
    <data noupdate="1">
        <record id="seq_sn_business_document" model="ir.sequence">
            <field name="name">Business Document Sequence</field>
            <field name="code">sn.business.document</field>
            <field name="prefix">DOC/</field>
            <field name="padding">5</field>
        </record>
    </data>
</odoo>
```

### 5.2 Dependency Scoping

* Always prepend external identifiers with explicit model dependencies scopes using the explicit `<span>module_name.record_id</span>` formatting paradigm.
* Any model utilizing cross-module attributes must assert dependency targets clearly via the `<span>depends</span>` key array defined inside `<span>__manifest__.py</span>`.

---

## Advanced Field Types & JSON Clean Sanitization

### 6.1 Strict JSON Column Interactivity

* Odoo 19 handles JSON operations systematically. When parsing input into `<span>fields.Json</span>` or complex `<span>fields.Domain</span>` types, sanitize arrays safely using `<span>sanitize_json</span>`.
* When pushing raw strings straight down into fallback `<span>fields.Text</span>` layers, explicitly structure and serialize payloads securely via `<span>json.dumps()</span>`.

```
import json
from odoo.tools import sanitize_json

class SnDataPipeline(models.Model):
    _name = 'sn.data.pipeline'

    # Advanced Type Native Handling
    payload = fields.Json(string="Clean Content")
    criteria = fields.Domain(string="Target Filter", model_name="res.partner")

    def process_incoming_payload(self, raw_dict):
        self.ensure_one()
        # Sanitize against structural injections
        clean_data = sanitize_json(raw_dict)
        self.write({'payload': clean_data})
```

---

## 3. i18n 翻译文件 (PO 文件) 处理规范

### 3.1 编码与格式（必须保持不变）
- PO 文件统一使用 **UTF-8** 编码、**CRLF** 行尾。
- 修改前后必须校验 CRLF 完整；若被破坏，立即用 `utf-8-sig` 编码 + `\r\n` 还原。

### 3.2 禁止用 shell 命令处理中文 PO
- **禁止**用 `echo`、`cat`、`sed`、`printf`、重定向 (`>`/`>>`) 读写或拼接含中文的 PO 内容——这是乱码的主要来源。
- 必须使用 Read / Write / Edit 专用工具操作 PO 文件。
- 批量解析时使用 `polib` 库，不要用正则表达式匹配 msgid/msgstr。

### 3.3 乱码自检（每次修改后必须执行）
- 验证文件中 **无 PUA 字符**（U+E000–U+F8FF）、**无 €**（U+20AC）、**无孤立 `?`**。
- 出现以上任一标记，说明编码链路已损坏，必须停止并用正确编码重写，不得交付。


## AI Refactoring & Anti-Pattern Red Flags

AI MUST flags the following common errors during code creation or code review tasks:

* **❌** **CRITICAL FAULT:** Outputting `<span><tree></span>` instead of `<span><list></span>`.
* **❌** **CRITICAL FAULT:** Emitting `<span>attrs="{'invisible': ...}"</span>` or `<span>states="draft"</span>`.
* **❌** **CRITICAL FAULT:** Declaring database restrictions using `<span>_sql_constraints = [...]</span>`.
* **❌** **CRITICAL FAULT:** Using legacy lists arrays like `<span>(0, 0, vals)</span>` inside XML data records or Python calculations. Replace immediately with `<span>Command</span>` API methods.
* **❌** **CRITICAL FAULT:** Omitting the `<span><t t-name="card"></span>` wrapper layout layer inside customized Kanban structural files.

## PowerShell + SSH 远程命令规范

1. PowerShell 不支持 Bash 的 here-doc（`<<EOF`）。本地多行内容使用 PowerShell here-string：
   - `@' ... '@`
   - `@" ... "@`
   但不要把 Bash/SQL/Python 多行内容直接嵌套在 `ssh "..."` 中。

2. 禁止在 PowerShell 中直接拼接包含以下内容的 SSH 命令：
   - SQL 比较符 `<`、`>`
   - `$()`、反引号
   - Python 字符串引号
   - Bash 变量 `$var`
   - 反斜杠转义 `\"`
   - 密码、Token、哈希
   PowerShell 会优先解析这些字符，导致远程命令尚未执行就发生本地 ParserError。

3. 动态 SQL、Python 脚本、密码哈希等内容，统一采用：
   - 本地生成 UTF-8 字节
   - Base64 编码
   - 通过 SSH 标准输入传输
   - 远程使用 `base64 -d` 解码执行
   不要把内容拼接到 SSH 命令参数中。

4. 推荐模式：

   ```powershell
   $content = @'
   ... SQL 或 Python ...
   '@

   $encoded = [Convert]::ToBase64String(
       [Text.Encoding]::UTF8.GetBytes($content)
   )

   ssh.exe wsd "echo $encoded | base64 -d | python3"
