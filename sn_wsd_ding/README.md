# sn_wsd_ding（钉钉用户对接）

## 功能概述

该模块用于把 Odoo 用户（`res.users`）与钉钉用户（`userid`）建立映射，主要能力：

- 在 `res.users` 上新增只读字段 `dingding_user_id`
- 支持按手机号查询钉钉 `userid`（单个/批量）
- 在“设置”里配置钉钉应用凭证（用于获取 access token 并调用钉钉接口）

## 依赖

- Odoo：19.0
- Python：`requests`

## 钉钉凭证与配置（最新认证方式）

钉钉开发者平台 “应用凭证”页常见字段与本模块配置对应关系：

- `Client ID（原 AppKey / SuiteKey）` → 填到 Odoo 设置：`DingTalk App Key`
- `Client Secret（原 AppSecret / SuiteSecret）` → 填到 Odoo 设置：`DingTalk App Secret`
- `App ID`（UUID） → 填到 Odoo 设置：`DingTalk App UUID`
- `AgentId` → 填到 Odoo 设置：`DingTalk Agent ID`（审批发起会用到）

模块会按钉钉 v1.0 方式获取 access token：

- `POST https://api.dingtalk.com/v1.0/oauth2/accessToken`
- body：`{"appKey": "<Client ID>", "appSecret": "<Client Secret>"}`

## 用户操作

### 1）配置钉钉应用参数

进入：`设置` → `DingTalk`

- 配置 `DingTalk App Key / App Secret / App UUID / Agent ID`

### 2）获取并写入钉钉 User ID（单个）

进入：`设置` → `用户与公司` → `用户`

- 打开一个用户
- 点击按钮：`获取钉钉 User ID`

要求：该用户在 Odoo 中已维护手机号（优先取 `res.users.mobile/phone` 或 `partner_id.mobile/phone`）。

### 3）批量获取钉钉 User ID（列表）

进入：`用户` 列表

- 在“动作”菜单执行：`Batch Fetch DingTalk User IDs`

## 常见问题

### 1）报错提示缺少权限（如 `qyapi_get_member`）

说明：钉钉接口权限按应用授予，需要在钉钉开发者平台为该应用申请并开通对应 scope。

处理：

- 打开报错中给出的开通链接，申请并授权对应 scope
- 重新在 Odoo 执行获取 `dingding_user_id`

