# 存储周期温度计 🌡️

监测 DRAM/NAND 存储周期所处阶段的自动化工具。每周一北京时间 08:30，GitHub Actions 调用
Claude API（联网搜索）按**固定规则**给 5 个信号打分，生成 `data.json` 上传到微信云开发 Storage，
微信小程序端用 `wx.request` 拉取并原生渲染温度计、信号卡与历史趋势。

五个信号（源自 2018 年周期顶部的复盘）：
现货价 vs 合约价倒挂（25%）、设备商存储订单增速（20%）、下游库存与囤货（20%）、
AI 需求引擎边际变化（20%）、卖方一致性与管理层话术（15%）。
总温度 0–100：<30 景气上行 / 30–50 过热前期 / 50–70 过热中期→顶部预警 / ≥70 拐点临近。

## 架构（v2）

```
GitHub Actions（每周一 UTC 00:30）
  └─ scripts/update.py
       ├─ anthropic SDK（base_url=中转网关，ANTHROPIC_BASE_URL 可覆盖）+ web_search 打分
       ├─ 本地重算加权总分、校验来源、累积 history.json（git 提交即审计轨迹）
       └─ 腾讯云 API 密钥 → DescribeEnvs 拿桶信息 → COS 直传 data.json
微信云开发 Storage（权限：所有用户可读）
  └─ https://<CdnDomain>/data.json  ←小程序 wx.request 直接拉取
```

## 部署步骤

### 一、腾讯云 / 微信侧
1. 微信开发者工具开通云开发，记下**环境 ID**（TCB_ENV）。
2. 腾讯云控制台 → 访问管理(CAM) → 创建**子账号**，仅授予 `QcloudTCBFullAccess` + `QcloudCOSFullAccess`，
   生成 API 密钥（SecretId/SecretKey）。**不要用主账号密钥。**
3. 云开发控制台 → 存储 → 权限设置：改为**「所有用户可读，仅创建者可读写」**（一次性）。

### 二、GitHub 侧
Settings → Secrets and variables → Actions，配置 4 个 Secrets：

| Secret | 内容 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key（与你的 base_url 网关配套的 key） |
| `TCB_SECRET_ID` | 腾讯云子账号 SecretId |
| `TCB_SECRET_KEY` | 腾讯云子账号 SecretKey |
| `TCB_ENV` | 云开发环境 ID |

可选 Variables：`ANTHROPIC_BASE_URL`（默认 `https://gw.claudeapi.com`，用官方 key 时设为
`https://api.anthropic.com`）、`CLAUDE_MODEL`（默认 `claude-sonnet-5`）、`TCB_API_REGION`（默认 `ap-shanghai`）。

然后 Actions → 「每周更新存储周期温度计」→ **Run workflow** 手动跑一次，
从日志末尾复制 **dataUrl**（形如 `https://7878-xxx.tcb.qcloud.la/data.json`）。

### 三、小程序端
1. `miniprogram/config.js`：填入上一步的 `dataUrl`。
2. `miniprogram/project.config.json`：填入你的 AppID。
3. 小程序后台 → 开发管理 → 开发设置 → **request 合法域名**：添加 dataUrl 的域名
   （`https://` 到 `.tcb.qcloud.la` 为止）。
4. 开发者工具编译预览。分发建议体验版（免审核）；正式上架类目选「工具 → 信息查询」，勿碰金融类目。

## 设计要点与红线

- **密钥隔离**：Claude key、腾讯云密钥只存在于 GitHub Secrets；小程序包内只有一个公开 URL。
- **打分可复现**：规则写死在 `RULEBOOK`，模型只负责"搜索事实+对号入座"；总分由脚本本地重算。
- **历史真实累积**：`history.json` 只由脚本追加，模型无权生成历史；跑失败宁缺一期，绝不回填。
- **宁缺毋假**：任一信号无真实来源链接即报错退出。
- **免责声明**：由 `data.json` 下发，页面底部展示。

## 常见问题

- **小程序 403** → 云存储权限没设「所有用户可读」。
- **request:fail** → dataUrl 域名没加进 request 合法域名。
- **Actions 报 DescribeEnvs 权限错误** → 子账号缺 TCB 授权，或 TCB_ENV 填错。
- **模型未返回 JSON / 搜索失败** → 中转网关可能不支持 web_search 服务端工具；
  将 `ANTHROPIC_BASE_URL` 设为官方 `https://api.anthropic.com` 并换用官方 key 验证。
- **数据不是最新** → CDN 缓存 5 分钟（脚本设了 max-age=300），小程序端已带时间戳穿透，网页直开可能滞后几分钟。
