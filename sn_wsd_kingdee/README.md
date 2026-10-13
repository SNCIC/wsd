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
- 金蝶 WebAPI SDK：本地 wheel，**不在 PyPI 上**，随本模块一起分发：
  `sn_wsd_kingdee/SDK_Python3.0_V8.2.0/python_sdk_v8.2.0/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl`

> ⚠️ **发行名 ≠ 导入名**：wheel 的文件名/发行名是 `kingdee.cdp.webapi.sdk`，但它装出来的可导入包是 **`k3cloud_webapi_sdk`**（wheel 内的 `top_level.txt` 即此）。
> 所以 `pip show kingdee.cdp.webapi.sdk` 有输出 **不等于** 代码可用；真正的判据是 `import k3cloud_webapi_sdk`。代码里的导入是 `from k3cloud_webapi_sdk.main import K3CloudApiSdk`（与官方 demo 一致），**不要**照着 wheel 文件名去改导入。

SDK 采用懒加载（`models/kingdee_client.py`），因此**未安装 wheel 时模块也能正常安装和配置**，只有在真正调用接口时才会报出带安装命令的错误提示。

`kingdee.cdp.webapi.sdk` 为 MIT 许可，声明依赖 `requests`、`urllib3`。

### SDK 目录里哪些要部署

| 内容 | 部署需要吗 | 说明 |
| :--- | :--- | :--- |
| `python_sdk_v8.2.0/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl` | **需要** | 运行时依赖的安装来源，随仓库一起带上即可保证任何新机器都能确定性安装 |
| `python_sdk_demo/` | 不需要 | 官方示例（含 `.idea`、`.pytest_cache`），仅供开发查接口用法 |
| `Python3.0SDK使用说明.docx` | 不需要 | 官方文档 |
| `python_sdk_demo/conf.ini` | **禁止部署** | 内含体验环境的真实 `AppID` / `AppSecret` / `AcctID`；已在仓库根 `.gitignore` 忽略（`**/SDK_Python3.0_V8.2.0/python_sdk_demo/conf.ini`），`git clone/pull` 不会带出 |

> 运行时真正被 import 的是**装在 Odoo 解释器里的包**，而不是这个目录本身；目录只是“安装来源”。

## 部署（正式环境）

Odoo **不会**自动安装本地 wheel（`external_dependencies` 只能从 PyPI 安装），必须手动装进**运行 Odoo 的那个解释器**。顺序：同步代码 → 停服务 → 装 SDK → 升级模块 → 起服务 → 验收。

### 1. 同步代码

把 `myaddons` 同步到服务器的 addons 目录（例：`/opt/odoo/odoo19/myaddons`）。若服务器是 git 仓库：

```
cd /opt/odoo/odoo19/myaddons
git fetch && git merge --ff-only origin/main
```

### 2. 安装 SDK（关键：用 Odoo 自己的解释器）

先查出 Odoo 实际使用的解释器，**不要**用裸 `python3` / `pip`（极易装到别的环境）：

```
ps -eo pid,user,args | grep -i odoo | head      # 例：/opt/odoo/venv/bin/python3 …/odoo-bin -c /etc/odoo19.conf
systemctl cat odoo19 | grep -i exec             # 容器部署则看 docker inspect <容器> | grep -i cmd
```

用同一个解释器安装模块内的 wheel，并立即自检：

```
PY=/opt/odoo/venv/bin/python3                   # ← 换成上一步查到的解释器
$PY -m pip install /opt/odoo/odoo19/myaddons/sn_wsd_kingdee/SDK_Python3.0_V8.2.0/python_sdk_v8.2.0/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl
$PY -c "import sys, k3cloud_webapi_sdk; print('SDK_OK', k3cloud_webapi_sdk.__file__, sys.executable)"
```

Windows 开发机：

```
.venv\Scripts\python.exe -m pip install "myaddons\sn_wsd_kingdee\SDK_Python3.0_V8.2.0\python_sdk_v8.2.0\kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl"
```

### 3. 升级模块并重启

```
systemctl stop odoo19
su - odoo -s /bin/bash -c "/opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin -c /etc/odoo19.conf -d <数据库名> -u sn_wsd_kingdee --stop-after-init --no-http"
systemctl start odoo19
```

（服务用户以 systemd 单元里的 `User=` 为准；`-d` 取实际库名，本例 `odoo19`。）

### 4. 验收

1. 设置 → Kingdee：填好 `Server URL / Account ID / User Name / App ID / App Secret` → 点 **Test Connection**，成功会提示“连接成功，返回 N 个数据中心”
2. 取一个物料点 **Save to Kingdee**，到 `Kingdee → Sync Logs` 看请求/响应报文
3. 若报“组织”相关错误，再补 `Organization Number`（该账套的组织编码）与 `Create Organization`

### 5. 排查「运行 Odoo 的解释器未安装金蝶 WebAPI SDK（No module named 'k3cloud_webapi_sdk'）」

该提示只说明**运行 Odoo 的解释器 import 不到这个包**。提示末尾会直接给出**可复制的安装命令**（由 `sys.executable` 与模块内 wheel 的绝对路径拼成），先照抄执行；若仍失败，再按序核查：

1. 用 `ps -eo pid,user,args | grep -i odoo` 找到真正的解释器（如 `/opt/odoo/venv/bin/python3`）
2. 用它验证：`<该解释器> -c "import k3cloud_webapi_sdk"`，再用 `-m pip show kingdee.cdp.webapi.sdk` 对照
3. 常见原因：装进了别的 venv / 系统 python；`pip install --user` 装到了另一个用户（Odoo 以 `odoo` 运行）；装在容器外而 Odoo 在容器内；Debian/Ubuntu 24.04 的 `externally-managed-environment` 拦截（实际未装成功）；装完没重启服务
4. 用同一解释器重装后 `systemctl restart odoo19`（多 worker 时确认全部重启）

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
| Material Unit | 物料计量单位：金蝶 `BD_UNIT` 编码（如 `001`=只、`GE`=个），写入物料的基准/库存/采购/销售等 7 个单位字段；留空按 `001` |
| Use Organization | 物料使用组织（`FUserOrgId`），留空则取创建组织 |
| Scheduled Material Refresh | 允许定时任务刷新已对接物料 |

配置完成后点 **Test Connection**，成功会提示返回的数据中心数量。

> 注意：`App Secret` 保存在 `ir.config_parameter` 中，数据库内为明文，请把设置页权限限制在管理员范围内。

## 用户操作

### 1）把物料推送到金蝶

进入 `库存/销售 → 产品`，打开某个产品：

1. 在“Kingdee”页签填写 `Kingdee Number`（留空则取产品的内部参考 `default_code`）；
   `Kingdee Unit` 留空则取 `设置 → Kingdee → Material Defaults` 里配置的物料计量单位
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
- **推送字段为最小集**（`FCreateOrgId` / `FUserOrgId` / `FNumber` / `FName` / 计量单位 7 项 / 可选 `FMaterialGroup`）。计量单位取 `Material Unit`（默认 `001`），可用物料的 `Kingdee Unit` 覆盖；如需同步规格、物料分组、单位组等，请在 `product.template._kingdee_prepare_save()` 中按项目的金蝶基础资料编码补齐
- 金蝶报表类接口（科目余额表、库存报表等）需要**先在金蝶中保存查询方案**，把方案 ID 放进请求参数
- 金蝶 SDK 内部使用 `verify=False` 并关闭了 `InsecureRequestWarning`，即不校验服务端证书
- SDK 实例按凭据缓存复用会话（含 Cookie），非线程安全，多线程下共用同一实例存在竞态；如需更高并发请自行在客户端层加锁
- 金蝶没有提供 Odoo 侧的回调入口，因此这里是**只有出站调用**的单向对接
