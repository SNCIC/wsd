# AGENTS.md — wsd 开发规范

本文件是 ZCode（以及所有贡献者）在本仓库开发 `sn_wsd_*` / `muk_web_*` 模块时必须遵守的规则。

## 注意

**1.多公司是 Odoo 默认行为，无需额外开发；但自定义模型必须遵守：① 加 `company_id` 字段（含 default）；② 唯一约束带 `company_id`（如 `unique(company_id, sn)`）；③ 跨公司关联字段加 `check_company=True`。**
**2.不允许考虑降级处理，现在是开发阶段，如果有问题处理老旧数据，也不能为了老旧数据给逻辑变更.**
**3.skill odoo-19  作为开发手册，指导odoo开发**
**4.所有确定的决策和文档都统一放在路径 `D:\workspace\odoo\odoo-19.0\wsd-doc`下。**


## 仓库与运行环境

- 本目录（`wsd/`）是独立 git 仓库（github.com/SNCIC/wsd），作为 Odoo 19 的 addons 路径之一挂载。
- 运行环境：Odoo 19，Python 3.12（`D:\ProgramDatas\Anaconda\envs\odoo19\python.exe`）。
- 两套并行环境，共用同一 PostgreSQL（localhost:5432，用户 `odoo19`）：

|        | 企业版（现状）                                              | 社区版（开发目标）                                                   |
| ------ | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| 源码   | `D:\odoo19e20250921-f`（企业模块混在 `odoo\addons` 内） | `D:\odoo19-community`（junction/hardlink 镜像，仅 659 个社区模块） |
| conf   | `D:\wsd\odoo.local.conf`                                  | `D:\wsd\odoo.community.conf`                                       |
| 端口   | 8069                                                        | 8070                                                                 |
| 数据库 | `mes`                                                     | `mes_community`（28 个 wsd/muk 模块全部可装，0 企业模块）          |
| 日志   | `D:\wsd\odoo-server.log`                                  | `D:\wsd\odoo-community-server.log`                                 |

- **企业版启动** `D:\ProgramDatas\Anaconda\envs\odoo19\python.exe D:\odoo19e20250921-f\odoo-bin -c D:\wsd\odoo.local.conf -d mes`
- **社区版启动** `D:\ProgramDatas\Anaconda\envs\odoo19\python.exe D:\odoo19-community\odoo-bin -c D:\wsd\odoo.community.conf`（访问 http://localhost:8070）
- 社区版升级模块把 odoo-bin 路径换成社区版并加 `-u <MOD> --stop-after-init`（库用 `-d mes_community`）。

### 社区版环境要点（务必遵守）

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
8. **po 引用行格式**：字段标签用 `model:ir.model.fields,field_description:模块.字段；` **视图/菜单等结构化翻译必须用** `model_terms`: 前缀（如 model_terms:ir.ui.view,arch_db:模块.视图id），写成 model: 会被静默丢弃且无报错。新增视图后优先用 Odoo 导出翻译（设置→翻译→导出）生成引用行，不要手写。

### 允许中文的位置

- `i18n/zh_CN.po`（**唯一**的中文存放点）。
- **代码注释 / docstring**（非用户可见，允许中文）。
- commit message、PR 描述、本文档等元信息。

### 翻译流程

1. 正确做法：**源码里一律写英文**，中文只出现在 `i18n/zh_CN.po`。运行时 Odoo 按 `zh_CN` locale 用 `.po` 把英文替换成中文显示。

> 注：仓库内少数遗留文件（如部分 `sn_wsd_maintenance`/`sn_wsd_mrp` 的 `string='设备…'`、`menu_views.xml` 的 `name="车间"`）违反了本规则。新写或改动代码时一律按本规则执行，顺手修到的可一并改正。

## 开发闭环：升级 → 重启 → 测试

每完成一个任务（加字段 / 改视图 / 改逻辑 / 改 `.po`），按需走这个闭环。命令在上级目录 `D:\workspace\odoo\odoo-19.0` 下执行。

> `odoo.local.conf` 开了 `dev_mode = reload`：**纯 Python 逻辑**改动会被运行中的服务器自动重载，无需重启；但**字段结构、selection、视图、data、security、manifest、`.po`** 的改动必须升级模块。

设当前模块名为 `MOD`（例如 `sn_wsd_workorder`），替换下面命令里的模块名即可。

### 1. 升级模块（同时重载翻译）

```bash
cd D:/workspace/odoo/odoo-19.0
.venv/Scripts/python.exe D:\workspace\odoo\odoo-19.0\odoo-bin -c odoo.local.conf -d mes -u sn_wsd_workorder --stop-after-init
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
