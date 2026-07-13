# 存储周期温度计 🌡️

监测 DRAM/NAND 存储周期所处阶段的自动化工具。每周一北京时间 08:30，GitHub Actions 调用
Claude API（联网搜索）按**固定规则**给 5 个信号打分，生成 `data.json` 上传到微信云开发存储，
微信小程序端原生渲染温度计、信号卡与历史趋势。

五个信号（源自 2018 年周期顶部的复盘）：
现货价 vs 合约价倒挂（25%）、设备商存储订单增速（20%）、下游库存与囤货（20%）、
AI 需求引擎边际变化（20%）、卖方一致性与管理层话术（15%）。
总温度 0–100：<30 景气上行 / 30–50 过热前期 / 50–70 过热中期→顶部预警 / ≥70 拐点临近。

## 目录结构

```
├── .github/workflows/weekly.yml   # 每周一 UTC 00:30（北京 08:30）自动运行
├── scripts/update.py              # 打分 + 上传云存储 + 累积历史
├── data/
│   ├── history.json               # 历史读数（真实累积，git 提交记录即审计轨迹）
│   └── data.json                  # 最新完整数据（同步上传到云存储的就是这份）
└── miniprogram/                   # 微信小程序（原生，无 web-view）
    ├── app.js / app.json / app.wxss / sitemap.json
    ├── config.js                  # ← 只需改这里：env + fileID（均非密钥）
    ├── project.config.json        # ← 填入你的小程序 AppID
    └── pages/index/               # 温度计页面四件套
```

## 部署步骤

### 第一步：微信侧准备
1. 在 [微信公众平台](https://mp.weixin.qq.com) 注册小程序（个人主体即可），记下 **AppID** 和 **AppSecret**。
2. 微信开发者工具 → 导入 `miniprogram/` 目录 → 点击「云开发」开通（免费额度足够），记下**环境 ID**。
3. 小程序后台 → 开发管理 → 开发设置 → **IP 白名单**：保持关闭状态（GitHub Actions 的出口 IP 是动态的，
   开了白名单 token 获取会失败）。若必须开启，需改用固定出口 IP 的方案（如自建代理）。

### 第二步：GitHub 侧
1. 新建**私有**仓库，把本目录全部推上去（`miniprogram/` 也可以一起放着，不影响）。
2. Settings → Secrets and variables → Actions，添加 4 个 Secrets：

   | Secret | 内容 |
   |---|---|
   | `ANTHROPIC_API_KEY` | Claude API key（console.anthropic.com 创建） |
   | `WX_APPID` | 小程序 AppID |
   | `WX_SECRET` | 小程序 AppSecret |
   | `TCB_ENV` | 云开发环境 ID |

3. Actions 页面 → 「每周更新存储周期温度计」→ **Run workflow** 手动跑一次。
4. 运行成功后，从日志末尾复制 **fileID**（形如 `cloud://env.xxxx/data.json`）。

### 第三步：小程序端配置
1. 编辑 `miniprogram/config.js`：填入 `env`（环境 ID）和 `fileID`（上一步复制的）。
2. 编辑 `miniprogram/project.config.json`：填入你的 AppID。
3. 开发者工具编译预览，看到温度计即成功。分发方式：
   - **体验版（推荐）**：上传代码 → 后台设为体验版 → 添加体验成员（无需审核，适合自用+朋友圈子）。
   - 正式上架：类目务必选择「工具 → 信息查询」，**不要选金融相关类目**；页面已内置免责声明。

## 设计要点与红线

- **密钥隔离**：Claude API key、AppSecret 只存在于 GitHub Secrets。小程序包内只有环境 ID 和
  fileID——这两者本身不是秘密（包可被反编译，任何秘密都不能进包）。
- **打分可复现**：规则写死在 `scripts/update.py` 的 `RULEBOOK` 中，模型只负责"搜索事实 + 按规则对号入座"；
  加权总分由脚本本地重算，不采用模型算术。
- **历史真实累积**：`history.json` 只由脚本追加、随 git 提交，模型无权生成历史；某周跑失败则该周缺一期，
  绝不回填编造。
- **宁缺毋假**：任一信号缺少真实来源链接时脚本直接报错退出，不发布无来源数据。
- **免责声明**：由 `data.json` 下发并在页面底部展示，措辞避免任何投资建议属性。

## 运行成本

GitHub Actions 免费额度内；云开发免费额度内（一个几 KB 的 JSON）；
Claude API 每周一次调用约 $0.1–0.3（含搜索），每月不到 1.5 美元。

## 常见问题

- **Actions 报 token 失败** → 检查 AppSecret 是否正确、IP 白名单是否关闭。
- **小程序报下载失败** → 检查 `config.js` 的 env/fileID；确认云存储中确实存在 `data.json`
  （云开发控制台 → 存储 可见）。
- **想改运行时间** → 编辑 `weekly.yml` 的 cron（注意是 UTC 时间）。
- **想换打分模型** → 仓库 Settings → Variables 或直接在 workflow 中加 `CLAUDE_MODEL` 环境变量
  （默认 `claude-sonnet-5`）。
