# 金蝶云星空对接 SOP（新增单据 / 基础资料必读）

> 目标：把"接一张新单据"变成一条固定工序。每张单据**只写两样东西**——识别编码与 payload
> （`_kingdee_number()` 与 `_kingdee_payload()`）；状态字段、动作、逐条错误隔离、日志、通知
> 全部由 `sn.wsd.kingdee.sync.mixin` 提供。
>
> 样板：物料 `models/product_template.py`（有子实体嵌套）、客户 `models/res_partner.py`（最小集）。

## 0. 一次性准备

| 项 | 位置 / 做法 |
| :--- | :--- |
| 凭据 | 设置 → Kingdee：`Server URL`（以 `/k3cloud/` 结尾）、`Account ID`、`User Name`、`App ID`、`App Secret` |
| 组织 | 同页 `Create Organization`（`FCreateOrgId`，多组织账套必填）、`Use Organization`（`FUseOrgId`，留空取前者） |
| 离线契约 | `odoo-kingdee/data/kingdee-openapi/`：**`fields_master.csv`（权威主索引，90,327 字段：字段名 / 必录 / 枚举 / 引用对象，**以账套为准**）**、`kingdee_api_catalog.csv`（28,595 接口）、`metadata/{formId}.json`（**平台登记版**完整字段树，仅需实体树时才用） |
| 探针（离线） | `tools/probe_form.py <formId>`：实体树、**账套必录**、引用目标、枚举取值、payload 骨架（默认读主索引；`--legacy` 才读平台版树） |
| 探针（在线，只读） | `tools/probe_live.py`：用 `odoo-bin shell < tools/probe_live.py` 跑，采真实值（枚举优先查主索引） |
| 试推（在线，**会写**） | `tools/try_save_customer.py`：直连 WebAPI 建一条 `ZZ-TEST-*` 客户 → 回读 → 删除，用来验证「元数据标的必录是否真的拦」。需 5 个 `KD_*` 环境变量（与 MCP 同名） |
| 纪律 | 测试数据一律 `ZZ-TEST-*` 前缀，验收后删除；**任何 formId/字段名都要有出处**，禁止凭命名习惯或 SDK demo 推测 |

## 1. 八步工序

| # | 步骤 | 命令 / 做法 | 产出与判据 |
| :---: | :--- | :--- | :--- |
| 1 | 定边界 | 与业务确认 | 方向（出站/入站）、对象、触发方式、幂等键、归属组织 |
| 2 | 查 formId 与操作 | `python tools/kingdee_catalog.py search 客户` → `ops BD_Customer` | 真实 formId + 操作清单（`Save/Submit/Audit/UnAudit/Delete/Push…`） |
| 3 | 查必录与字段树 | `python tools/kingdee_fields.py must BD_Customer`；`python tools/probe_form.py BD_Customer` | **账套**必录清单（含 `entityKey`、`lookUpObjectID`、枚举取值）+ payload 骨架。两个工具都读主索引 `fields_master.csv`，**不要改去读平台版 `metadata/`**（必录会偏少） |
| 4 | 只读对齐真实数据 | 改 `tools/probe_live.py` 的 `FORM_ID/FIELD_KEYS`，走 `iter_bill_query` | 字段确有值；**枚举取值**（元数据不含 options，只能实测） |
| 5 | 定嵌套结构 | 看元数据 `entityKey` | 单据头平铺、子实体按 entityKey 嵌套（实测：`FBillHead` 的字段也要平铺） |
| 6 | 可写字段探测 | 逐字段加入 payload 试 `Save`，被拒即剔除 | 一份该账套**真能写**的字段集（必录 ≠ 可写） |
| 7 | 试推 → 回读 → 删除 | `Save` → `View`/`BillQuery` 比对 → `Delete`；客户可直接跑 `python tools/try_save_customer.py`（自带 `ZZ-TEST-*` 命名、回读与自动清理） | 回读逐字段一致；测试数据不留痕 |
| 8 | 落模块 | 见下节 + 视图/动作/权限/译文/README | `-u` 零错误、表单可渲染、验收判据全过 |

**两步不能省**：第 4 步（只读对齐，否则类型/枚举错了后面全返工）与第 7 步（回读验收）。

## 2. mixin 契约：新单据要写什么

```python
class ResPartner(models.Model):
    _inherit = ["res.partner", "sn.wsd.kingdee.sync.mixin"]

    _kingdee_form_id = "BD_Customer"          # ① 金蝶业务对象

    def _kingdee_number(self):                # ② 识别编码（FNumber）
        return (self.kingdee_number or self.ref or "").strip()

    def _kingdee_payload(self, client):       # ③ 字段映射（含实体嵌套）
        return {...}
```

| 接口 | 必填 | 说明 |
| :--- | :---: | :--- |
| `_kingdee_form_id` | ✅ | 如 `BD_MATERIAL`、`BD_Customer` |
| `_kingdee_number()` | ✅ | 决定幂等：同编码 `Save` 即更新 |
| `_kingdee_payload(client)` | ✅ | 只放该账套**真能写**的字段；引用型一律 `{"FNumber": ...}` |
| `_kingdee_apply_readback(data)` | ⭕ | 回读后把额外字段写回 Odoo |

自动获得：`kingdee_number / kingdee_name / kingdee_master_id / kingdee_sync_state /
kingdee_last_sync_at / kingdee_sync_message / kingdee_log_ids` 状态字段、
`action_kingdee_save / submit / audit / unaudit / pull / delete`（列表批量动作同理）、
逐条 savepoint 隔离、通知、日志关联，以及 `UNIQUE(kingdee_number)` 约束。

## 3. 验收判据（每张单据都要过一遍）

| 项 | 判据 |
| :--- | :--- |
| 加载 | 本地与服务器 `-u sn_wsd_kingdee` **exit 0**、无 `ERROR/CRITICAL/Traceback` |
| 表单 | 该模型的 form 视图能渲染（可调用域会按模型解析，如 `kingdee_log_ids`） |
| 约束 | 目标表存在 `UNIQUE(kingdee_number)` 索引 |
| 重构回归 | 若动了 payload 代码：**改动前后 payload 逐字段一致**（见 §5） |
| 接口 | `Test Connection` 提示"凭据已通过 `BD_MATERIAL` 查询校验"；`Sync Logs` 无 error |
| 回读 | `Save` 后 `Refresh from Kingdee`，编码/名称/内码与该单据一致 |
| 清理 | 测试数据已在金蝶删除（表单上的 **Delete in Kingdee**），Odoo 测试记录已删 |
| 译文 | `zh_CN.po` 覆盖新串（0 未翻译、条目带 `#. module:` 注释与引用，否则 `-u` 会崩） |
| 服务 | `systemctl is-active odoo19` + 首页 200 |

## 4. 实测坑清单（都是踩过的）

| # | 坑 | 正确做法 |
| :---: | :--- | :--- |
| 1 | `GetDataCenters` **免鉴权**，凭据错也返回 | 验凭据用最轻量业务查询（本模块已内置） |
| 2 | `TopRowCount` 是**绝对终止行号**，不是页大小 | 用 `iter_bill_query()`；手写须 `StartRow + Limit` |
| 3 | `MsgCode` 语义官方未公开 | `1` 凭据错（**重试无效**）、`4` 表单不存在、`8` 参数为空、`9` 字段名不存在 |
| 4 | 元数据「必录」≠ WebAPI「可写」；**子实体的「必录」在子实体整体不传时不触发** | 第 6 步逐字段探测；以实测为准。实测 `BD_Customer`：账套元数据标 `FTTel`（联系人子实体 `FT_BD_CUSTCONTACT`）必录，但不传联系人子实体**仍能保存成功** —— 全量 349 条现网客户的 `FTTel` 都是空的。验证脚本：`tools/try_save_customer.py` |
| 5 | 子实体字段平铺被拒（如 `FErpClsID` 会被默认成"外购"） | 按 `entityKey` 嵌套；单据头字段平铺 |
| 6 | SDK demo 的 `FUserOrgId` 已失效 | 正确为 `FUseOrgId`；字段名一律查元数据 |
| 7 | 单次查询上限 2000 行 | 分页；`page_size` 默认 2000 |
| 8 | po 条目缺 `#. module:` 注释会让 `-u` 直接 255 崩 | 译文用 `trans_export()` 生成/合并，勿手改结构 |
| 9 | 多组织：单据落错组织 | 写入必带 `FCreateOrgId`/`FUseOrgId` |
| 10 | 密钥易外泄（明文入库、日志、终端） | 不进日志；终端输出只报长度；泄露后轮换 |
| 11 | **平台版元数据 ≠ 账套元数据**：`metadata/{formId}.json` 是开放平台**登记版**。实测 `BD_Customer` 平台版只标 3 项必录，账套版**另外**标了 `FSELLER`/`FSALDEPTID`/`FTTel` | **查主索引 `fields_master.csv`（账套优先），不要只读平台版树** —— `tools/probe_form.py` 默认已改读主索引。再按第 6 步用真实 `Save` 确认「必录 ≠ 可写」，并把账套的额外要求写进 `_kingdee_check_ready()` |
| 12 | **业务规则不在元数据里**：本账套的客户**必须先提交（Submit）再审核（Audit）**，销售部门还必须是**销售类**部门（如 `ZN0801` 销售一部，`ZN01` 总经办会被当成未填） | 第 4 步顺便读几条已有单据的真实取值；第 7 步按完整生命周期（Save→Submit→Audit→Un-audit→Delete）走一遍 |

## 5. 重构时的 payload 回归（工具化做法）

改 `_kingdee_payload()`（例如抽公共基类）前，先在**服务器**上把当前 payload 存成基线：

```
odoo-bin shell -c /etc/odoo19.conf -d odoo19 --no-http < <(echo "$(cat)" <<'PY'
import base64, json
out = {}
for rec in env["product.template"].search([], limit=6, order="id"):
    try:
        number, model = rec._kingdee_prepare_save()
        out[str(rec.id)] = {"number": number, "model": model}
    except Exception as err:
        out[str(rec.id)] = {"error": str(err)}
print("PAYLOAD_B64=" + base64.b64encode(json.dumps(out, ensure_ascii=False, sort_keys=True).encode()).decode())
PY
)
```

部署改动后用同一段代码再算一次，逐字节比对（序列化时 `sort_keys=True`）。本模块抽 mixin 时即用此法
证明物料 payload **零变化**。

## 6. 已对接清单

| Odoo 模型 | formId | 必录 | 推送字段 | 默认值来源 |
| :--- | :--- | :---: | :--- | :--- |
| `product.template` | `BD_MATERIAL` | 35（账套版；平台版 36，多标 `FMaterialGroup`） | 最小集：组织 ×2、`FNumber`/`FName`、7 个计量单位、属性/类别/分组 + 20 项账套固定值 | `kingdee_client.DEFAULTS` + 设置页 + 物料级覆盖 |
| `res.partner` | `BD_Customer` | **5**（账套版；平台版仅 3）。子实体 `FTTel` 虽标必录但**已实测不强制** | 组织 ×2、`FNumber`/`FName`、`FTRADINGCURRID`（结算币别）、`FSELLER`（销售员）、`FSALDEPTID`（销售部门） | `DEFAULTS.customer_*` + 设置页 + 伙伴级覆盖；销售员/销售部门须先配置，`_kingdee_check_ready()` 会提前报错 |

> 待接（按建议顺序）：`STK_InStock`（采购入库，对接现有三步入库/IQC）→ `SAL_SaleOrder` /
> `PUR_PurchaseOrder` → `PRD_*` → 报表（`GetSysReportData` 需先在金蝶保存查询方案）。

**入站（金蝶 → Odoo）**：物料有两个入口，共用同一份字段清单
（`models/product_template.py` 的 `KINGDEE_MATERIAL_FIELDS`）与同一份映射：

| 入口 | 机制 | 范围 |
| :--- | :--- | :--- |
| 产品表单 `Refresh from Kingdee` | `View` 单条回读 → 钩子 `_kingdee_apply_readback()` | 一条 |
| 菜单 `Kingdee → Import Materials` | `BillQuery` 分页 → `_kingdee_import_materials()` | 批量，可过滤/限条，`Preview` 预演不写入 |

入站**只写「出站读得到的字段」**（编码/名称/物料属性/物料类别/物料分组/计量单位 + 同步状态），
故「导入后再推送」逐字段不变；名称只在新建时写入。客户尚未实现入站。
