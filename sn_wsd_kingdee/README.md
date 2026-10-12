# sn_wsd_kingdee（金蝶云星空对接）

## 功能概述

通过金蝶官方的 Python 版 WebAPI SDK（`k3cloud_webapi_sdk`）对接金蝶云星空（K/3 Cloud）：

- 在“设置 → Kingdee”里维护 WebAPI 连接参数与物料默认组织
- 一键测试连接（不需要先保存设置即可用当前填写的参数试连）
- 物料主数据单向/双向同步：`BD_MATERIAL` 的保存、提交、审核、反审核、查看
- 每次调用都落库到“金蝶同步日志”，含请求/响应报文、耗时、错误信息；**失败的日志用独立事务写入，不会因为后续报错回滚而丢失**
- 定时任务刷新已对接物料（默认关闭）
- 物料表单新增“Kingdee”页签，可查看同步状态与相关日志

## 依赖

- Odoo：19.0
- Python：`requests`（Odoo 必装）
- 金蝶 WebAPI SDK：本地 wheel，**不在 PyPI 上**，需要单独安装：
  `SDK_Python3.0_V8.2.0/python_sdk_v8.2.0/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl`

SDK 采用懒加载（`models/kingdee_client.py`），因此**未安装 wheel 时模块也能正常安装和配置**，只有在真正调用接口时才会报出带安装命令的错误提示。

安装命令（用项目虚拟环境）：

```
.venv\Scripts\python.exe -m pip install "SDK_Python3.0_V8.2.0\python_sdk_v8.2.0\kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl"
```

`kingdee.cdp.webapi.sdk` 为 MIT 许可，声明依赖 `requests`、`urllib3`。

## 金蝶侧准备

1. 在金蝶云星空产品中打开「第三方系统登录授权」，创建应用并记下 **应用ID / 应用密钥 / 授权用户**
2. 在 `open.kingdee.com` 的同一授权项中取得 **数据中心标识（AcctID，即账套ID）**
3. 确认 WebAPI 服务已开通，并将 Odoo 服务器出口 IP 加入白名单
4. 确认服务地址：公有云/体验环境 `https://apiexp.open.kingdee.com/k3cloud/`；私有云为 `https://<域名>/k3cloud/`，必须以 `/k3cloud/` 结尾
5. 单据字段名（`FNumber`、`FName` 等）需查阅金蝶 WebAPI 文档或产品内的接口示例，SDK 本身不携带字段元数据

## Odoo 侧配置

进入 `设置 → Kingdee`：

| 配置项 | 说明 |
| :--- | :--- |
| Server URL | 金蝶环境地址，以 `/k3cloud/` 结尾 |
| Account ID | 数据中心标识（AcctID） |
| User Name | 授权的金蝶用户 |
| App ID / App Secret | 第三方系统登录授权的应用 ID 与密钥 |
| Organization Number | 组织编码，启用多组织时才需要 |
| Locale ID | 账套语系，默认 2052 |
| Connection / Request Timeout | 连接与读取超时（秒） |
| Create Organization | 物料创建组织（`FCreateOrgId`），**必填** |
| Use Organization | 物料使用组织（`FUserOrgId`），留空则取创建组织 |
| Scheduled Material Refresh | 允许定时任务刷新已对接物料 |

配置完成后点 **Test Connection**，成功会提示返回的数据中心数量。

> 注意：`App Secret` 保存在 `ir.config_parameter` 中，数据库内为明文，请把设置页权限限制在管理员范围内。

## 用户操作

### 1）把物料推送到金蝶

进入 `库存/销售 → 产品`，打开某个产品：

1. 在“Kingdee”页签填写 `Kingdee Number`（留空则取产品的内部参考 `default_code`）
2. 点击 **Save to Kingdee** → 状态变为 `Saved`
3. 需要走审批流时依次点 **Submit** → **Audit**；需要退回时点 **Un-audit**
4. 点击 **Refresh from Kingdee** 可按物料编码回读金蝶侧的编码/名称/内码

批量操作：在“产品”列表勾选多行 → `动作` 菜单 → `Kingdee: Save Materials / Audit Materials / Refresh Materials`。

### 2）排查问题

进入 `Kingdee → Sync Logs`：

- 默认按时间倒序，错误行标红；可用「Errors」筛选
- 打开某条日志可看到完整的请求/响应报文与错误信息
- 通过“关联记录”列或 `Open Related Record` 按钮跳回对应产品

### 3）启用定时刷新（可选）

1. 在 `设置 → Kingdee` 勾选 `Scheduled Material Refresh` 并保存
2. 进入 `设置 → 技术 → 计划任务`，找到 `Kingdee: refresh linked materials`，把“有效”打开
3. 该任务每次取 50 条已对接物料，按上次同步时间从早到晚刷新

## 已知边界

- 目前实现的是物料主数据（`BD_MATERIAL`）。其它单据（销售订单、采购订单、生产订单等）请复用 `sn.wsd.kingdee.client` 的方法：`save` / `batch_save` / `bill_action` / `execute_bill_query` / `bill_query` / `view` / `get_sys_report_data` / `execute`，把 `FormId` 与字段换成目标单据即可
- **推送字段为最小集**（`FCreateOrgId` / `FUserOrgId` / `FNumber` / `FName` / 可选 `FMaterialGroup`）。如需同步规格、计量单位、基本计量单位等，请在 `product.template._kingdee_prepare_save()` 中按项目的金蝶基础资料编码补齐
- 金蝶报表类接口（科目余额表、库存报表等）需要**先在金蝶中保存查询方案**，把方案 ID 放进请求参数
- 金蝶 SDK 内部使用 `verify=False` 并关闭了 `InsecureRequestWarning`，即不校验服务端证书
- SDK 实例按凭据缓存复用会话（含 Cookie），非线程安全，多线程下共用同一实例存在竞态；如需更高并发请自行在客户端层加锁
- 金蝶没有提供 Odoo 侧的回调入口，因此这里是**只有出站调用**的单向对接
