#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储周期温度计 · 每周更新脚本（v2）
- Claude 调用：官方 anthropic SDK，base_url 指向中转服务（可用 ANTHROPIC_BASE_URL 覆盖）
- 上传：腾讯云 API 密钥（TCB_SECRET_ID/TCB_SECRET_KEY）直传云开发 Storage 底层 COS 桶
- 小程序端改用 wx.request 拉取公开下载域名上的 data.json
密钥全部来自环境变量（GitHub Secrets），本脚本及产出物中不含任何密钥。
"""
import json
import os
import re
import sys
import datetime

# ---------- 环境变量与启动检查 ----------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not ANTHROPIC_API_KEY:
    sys.exit("[错误] 环境变量 ANTHROPIC_API_KEY 为空，请在 GitHub Secrets 中配置")

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://gw.claudeapi.com").strip()
TCB_SECRET_ID = os.environ.get("TCB_SECRET_ID", "").strip()
TCB_SECRET_KEY = os.environ.get("TCB_SECRET_KEY", "").strip()
TCB_ENV = os.environ.get("TCB_ENV", "").strip()
if not (TCB_SECRET_ID and TCB_SECRET_KEY and TCB_ENV):
    sys.exit("[错误] TCB_SECRET_ID / TCB_SECRET_KEY / TCB_ENV 不能为空")

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "20000"))  # 搜索结果计入输出token，需留足余量
CLOUD_PATH = os.environ.get("CLOUD_PATH", "data.json")
TCB_API_REGION = os.environ.get("TCB_API_REGION", "ap-shanghai")  # tcb 接口接入地域

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(ROOT, "data", "history.json")
DATA_PATH = os.path.join(ROOT, "data", "data.json")

WEIGHTS = [0.25, 0.20, 0.20, 0.20, 0.15]
SIGNALS_META = [
    {"id": 1, "name": "现货价 vs 合约价倒挂", "lead": "领先约1–2个季度 · 最直接的拐点触发器"},
    {"id": 2, "name": "设备商存储订单增速", "lead": "领先12–18个月 · 供给释放的先行指标"},
    {"id": 3, "name": "下游库存与囤货行为", "lead": "领先2–3个季度 · 表观需求虚增的检验器"},
    {"id": 4, "name": "最大需求引擎的边际变化（AI capex）", "lead": "核心变量 · 上轮是手机+挖矿，本轮是云厂商"},
    {"id": 5, "name": "卖方一致性与管理层话术", "lead": "反向指标 · 预测年份后移=警觉信号"},
]

RULEBOOK = """① 现货vs合约（权重25%）：0-25 现货显著高于合约且持续上涨；25-50 现货仍高但涨幅收窄/成交清淡/买方抵制报价；50-75 价差收敛至±3%以内或现货连跌4周；75-100 现货跌破合约（倒挂确认）
② 设备订单（权重20%）：0-25 存储厂capex同比下降或持平；25-50 温和回升<+15%；50-75 同比+15~30%或有新建fab宣布；75-100 同比>+30%且多座新fab并行+新玩家（CXMT等）同步扩产
③ 下游库存（权重20%）：0-25 下游库存<4周且无长约锁量；25-50 库存正常但长约/预订比例上升；50-75 长约锁量盛行+"全年售罄"话术+重复下单迹象；75-100 渠道库存>10周或大客户砍单/毁约长约
④ 需求引擎（权重20%）：0-25 云厂商capex指引持续上调无一家松口；25-50 指引仍增长但增速见顶/出现回报率质疑声；50-75 有云厂商下调指引或推迟数据中心项目；75-100 ≥2家大厂明确削减capex
⑤ 叙事一致性（权重15%）：0-25 卖方分歧大、管理层谨慎提供给纪律；25-50 一致看多但预测期限稳定；50-75 短缺预测年份开始后移、"这次不一样"叙事流行；75-100 预测后移至3年以上+龙头上市/巨额融资+几乎无人看空"""


def beijing_today() -> str:
    tz = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz).strftime("%Y-%m-%d")


def stage_of(total: int):
    if total < 30:
        return "景气上行期", "价格上行初中段，信号面干净。主要风险是踏空而非站岗。"
    if total < 50:
        return "过热前期", "上行动能仍在，但供给端/叙事端开始积累矛盾，需每周核对领先信号。"
    if total < 70:
        return "过热中期 → 顶部预警", "多个领先信号亮黄/红灯。历史上此阶段距拐点约6–12个月，应制定退出触发条件。"
    return "拐点临近", "领先信号组合确认。2018年教训：此时叙事最强、股价未必已跌，正是最难卖出的时刻。"


def build_prompt(history: list) -> str:
    last = history[-1] if history else None
    last_txt = (
        f"上期读数（{last['date']}）：五信号分数 {last['s']}，总温度 {last['total']}。摘要：{last.get('note','无')}"
        if last else "无上期读数（首次运行）。"
    )
    return f"""你是存储芯片（DRAM/NAND）周期监测助手。今天是 {beijing_today()}。请完成：

一、用网络搜索逐一核实以下 5 个维度的最近两周动态（优先 TrendForce、DRAMeXchange、Tom's Hardware、公司财报与官方指引）：
1. DRAM/NAND 现货价 vs 合约价：最新周度现货走势、成交活跃度、现货与合约价差方向
2. 存储设备订单/capex：三星、SK海力士、美光、CXMT 的 capex 与新 fab 进展、WFE 装机节奏
3. 下游库存与囤货：OEM/渠道库存周数、长约锁量、售罄/砍单/递延交货迹象
4. AI 需求引擎：微软/谷歌/亚马逊/Meta 最新 capex 指引及措辞变化、有无下调或推迟
5. 叙事与一致性：管理层短缺预测年份是否又后移、卖方有无新增看空声音

二、严格按以下固定规则为每个信号打 0-100 分（分数越高越接近周期顶部），不得偏离规则自由发挥：
{RULEBOOK}

三、{last_txt}

四、只输出一个 JSON 对象（不要输出任何其他文字、不要用代码块包裹），结构如下：
{{
  "signals": [
    {{"score": <0-100整数>, "reading": "<60-100字中文本期读数，含关键数字>", "sources": [{{"title": "<来源名>", "url": "<真实URL>"}} 最多2条]}},
    ... 共5项，严格按上面1-5的顺序 ...
  ],
  "comment": "<100-180字本期点评：与上期相比哪些信号升温/降温、下周最该盯什么>",
  "note": "<一句话本期摘要，30字以内>"
}}

硬性要求：每个信号至少 1 条 sources 且 url 必须来自你本次搜索到的真实网页，严禁编造链接；打分只依据搜到的事实，找不到新信息的维度沿用上期分数并在 reading 中注明"本期无增量信息"。"""


def extract_json(text: str):
    """从模型输出中稳健提取 JSON 对象：
    优先扫描每个 '{' 起点用 raw_decode 尝试解析（正确处理字符串内的大括号），
    只接受含 signals 键的 dict，避免误抓正文/错误信息里的大括号片段。"""
    dec = json.JSONDecoder()
    for mm in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[mm.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and "signals" in obj:
            return obj
    return None


def call_claude(history: list) -> dict:
    """官方 anthropic SDK + 中转 base_url。带重试与诊断输出。"""
    import anthropic

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=ANTHROPIC_BASE_URL,
        timeout=900.0,
    )
    prompt = build_prompt(history)
    last_text = ""
    for attempt in range(1, 4):
        print(f"[信息] 调用模型，第 {attempt}/3 次尝试 ...")
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            print(f"[警告] 第 {attempt} 次 API 调用异常：{e}")
            continue

        # 诊断：本次响应有没有真的联网搜索
        searched = any(
            getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")
            for b in msg.content
        )
        if not searched:
            print("[警告] 本次响应中没有任何联网搜索记录——中转网关可能未执行/不支持 "
                  "web_search 服务端工具，结果可信度存疑")

        last_text = "".join(
            b.text for b in msg.content if getattr(b, "type", "") == "text"
        )
        print(f"[信息] stop_reason={msg.stop_reason}，文本长度={len(last_text)}，联网搜索={searched}")

        if msg.stop_reason == "max_tokens":
            print(f"[警告] 输出被 max_tokens={MAX_TOKENS} 截断——JSON 大概率不完整。"
                  "若反复出现，请在仓库 Variables 中调大 CLAUDE_MAX_TOKENS")

        obj = extract_json(last_text)
        if obj is not None:
            if not searched and attempt < 3:
                # 没搜索的结果视为不可信，重试
                print("[信息] 无搜索记录的结果不予采用，重试 ...")
                continue
            return obj
        print(f"[警告] 第 {attempt} 次未能解析出合法 JSON，原文前 500 字：\n{last_text[:500]}")

    sys.exit("[错误] 连续 3 次未获得含 signals 的合法 JSON。完整原文如下（前 3000 字），"
             "若始终无搜索记录/非 JSON，多为中转网关不支持 web_search 或不稳定，"
             "建议将 ANTHROPIC_BASE_URL 设为官方 https://api.anthropic.com 并改用官方 key：\n"
             + last_text[:3000])


def validate(result: dict) -> list:
    sigs = result.get("signals")
    if not isinstance(sigs, list) or len(sigs) != 5:
        sys.exit("[错误] signals 必须是长度为 5 的数组")
    for i, s in enumerate(sigs):
        sc = s.get("score")
        if not isinstance(sc, (int, float)) or not (0 <= sc <= 100):
            sys.exit(f"[错误] 信号{i+1} 分数非法：{sc}")
        s["score"] = int(round(sc))
        srcs = [x for x in s.get("sources", []) if str(x.get("url", "")).startswith("http")]
        if not srcs:
            sys.exit(f"[错误] 信号{i+1} 缺少真实来源链接——宁可失败也不发布无来源数据")
        s["sources"] = srcs[:4]
        if not s.get("reading"):
            sys.exit(f"[错误] 信号{i+1} 缺少 reading")
    return sigs


def tcb_upload(content: bytes):
    """用腾讯云 API 密钥上传到云开发 Storage 底层 COS 桶，并打印公开访问 URL。
    「所有用户可读」在云开发控制台→存储→权限设置里配置（一次性操作）。
    建议使用仅授予 TCB+COS 权限的子账号密钥，勿用主账号密钥。"""
    from tencentcloud.common import credential
    from tencentcloud.tcb.v20180608 import tcb_client, models
    from qcloud_cos import CosConfig, CosS3Client

    cred = credential.Credential(TCB_SECRET_ID, TCB_SECRET_KEY)
    tcb = tcb_client.TcbClient(cred, TCB_API_REGION)
    req = models.DescribeEnvsRequest()
    req.EnvId = TCB_ENV
    resp = tcb.DescribeEnvs(req)
    envs = [e for e in (resp.EnvList or []) if e.EnvId == TCB_ENV]
    if not envs or not envs[0].Storages:
        sys.exit(f"[错误] 未找到环境 {TCB_ENV} 或其存储信息（检查 TCB_ENV 与密钥权限）")
    st = envs[0].Storages[0]  # Region / Bucket / CdnDomain

    cos = CosS3Client(CosConfig(Region=st.Region, SecretId=TCB_SECRET_ID, SecretKey=TCB_SECRET_KEY))
    cos.put_object(
        Bucket=st.Bucket,
        Key=CLOUD_PATH,
        Body=content,
        ContentType="application/json; charset=utf-8",
        CacheControl="max-age=300",
    )
    url = f"https://{st.CdnDomain}/{CLOUD_PATH}"
    print("=" * 64)
    print("上传成功。小程序端 config.js 需要的 dataUrl（恒定不变，只需配置一次）：")
    print(f"  {url}")
    print("请确认两件事（均为一次性配置）：")
    print("  1) 云开发控制台→存储→权限设置：改为「所有用户可读，仅创建者可读写」")
    print(f"  2) 小程序后台→开发设置→request合法域名：添加 https://{st.CdnDomain}")
    print("=" * 64)


def main():
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)

    result = call_claude(history)
    sigs = validate(result)

    # 总分由脚本本地重算，不采用模型给出的任何合计值
    scores = [s["score"] for s in sigs]
    total = int(round(sum(sc * w for sc, w in zip(scores, WEIGHTS))))
    stage, stage_desc = stage_of(total)
    today = beijing_today()

    # 真实累积历史：同日期覆盖（重跑场景），否则追加；绝不由模型生成历史
    entry = {"date": today, "s": scores, "total": total, "note": result.get("note", "")}
    history = [h for h in history if h["date"] != today] + [entry]
    history.sort(key=lambda h: h["date"])

    data = {
        "updated": today,
        "total": total,
        "stage": stage,
        "stage_desc": stage_desc,
        "weights": WEIGHTS,
        "signals": [
            {**meta, "weight": WEIGHTS[i], "score": sigs[i]["score"],
             "reading": sigs[i]["reading"], "sources": sigs[i]["sources"]}
            for i, meta in enumerate(SIGNALS_META)
        ],
        "comment": result.get("comment", ""),
        "history": history,
        "disclaimer": "本页面为个人研究用途的公开信息聚合，由程序按固定规则自动生成，可能存在错误或延迟，不构成任何投资建议。",
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    with open(DATA_PATH, "wb") as f:
        f.write(payload)

    print(f"本期读数 {today}：signals={scores} total={total} 阶段={stage}")
    tcb_upload(payload)


if __name__ == "__main__":
    main()
