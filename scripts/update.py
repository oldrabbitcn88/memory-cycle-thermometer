#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储周期温度计 · 每周更新（v3 新口径）
模型只负责【提取原始指标】，分数由 scoring.py 机械映射——模型不再打分。
季度类指标带 asof 新鲜度控制：发布日未变则沿用上期，杜绝无信息期的虚假微调。
"""
import json, os, re, sys, datetime
import scoring as sc

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not ANTHROPIC_API_KEY:
    sys.exit("[错误] ANTHROPIC_API_KEY 为空")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://gw.claudeapi.com").strip()
TCB_ID  = os.environ.get("TCB_SECRET_ID", "").strip()
TCB_KEY = os.environ.get("TCB_SECRET_KEY", "").strip()
TCB_ENV = os.environ.get("TCB_ENV", "").strip()
if not (TCB_ID and TCB_KEY and TCB_ENV):
    sys.exit("[错误] TCB_SECRET_ID / TCB_SECRET_KEY / TCB_ENV 不能为空")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "20000"))
CLOUD_PATH = os.environ.get("CLOUD_PATH", "data.json")
TCB_REGION = os.environ.get("TCB_API_REGION", "ap-shanghai")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history_v3.json")
OUT  = os.path.join(ROOT, "data", "data.json")

NAMES = ["现货价 vs 合约价", "设备商存储订单", "下游库存与囤货", "需求引擎(AI capex)", "卖方一致性与话术"]
LEADS = ["领先1–2季度 · 主触发器", "领先12–18个月 · 背景条件", "领先2–3季度",
         "核心变量 · 门槛条件", "反向指标 · 背景条件"]


def bj_today():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")


PROMPT = """你是数据提取员，**不要打分、不要给结论**。今天是 {today}。请联网检索并只回填下列原始指标。

上期已知指标（若本期查不到更新的数据，把 asof 原样保留，数值也原样保留）：
{prev}

需要提取：
1. TrendForce 主流 DDR4 1Gx8 3200MT/s 现货价：最新一期与前一期的美元价格及各自日期
2. 现货连续下跌周数（若在上涨则填 0）
3. 存储厂 capex 同比增速%、在建或已宣布新 fab 数、是否有新玩家(CXMT等)扩产，及数据发布日
4. 下游/渠道库存周数、是否存在长约锁量、是否有"售罄"话术、是否出现砍单或毁约，及数据发布日
5. 云厂商中明确削减或推迟资本开支的家数、增速是否见顶、是否出现回报率质疑，及数据发布日
6. 管理层短缺预测覆盖年数（如"缺到2030"则从今年起算）、公开看空方数量、是否有龙头上市/巨额融资，及数据发布日
7. Roundhill Memory ETF (代码 DRAM) 最新收盘价与其52周高点

只输出一个 JSON，不要代码块包裹：
{{"spot":{{"latest_date":"YYYY-MM-DD","latest":<美元数>,"prev_date":"YYYY-MM-DD","prev":<美元数>,"weeks_down":<整数>,"at_record":<true/false>}},
 "capex":{{"yoy_pct":<数>,"new_fabs":<整数>,"new_entrant":<bool>,"asof":"YYYY-MM-DD"}},
 "inventory":{{"weeks":<数>,"lta":<bool>,"sellout":<bool>,"cancel":<bool>,"asof":"YYYY-MM-DD"}},
 "demand":{{"n_cutting":<整数>,"peaked":<bool>,"doubt":<bool>,"asof":"YYYY-MM-DD"}},
 "narrative":{{"years_out":<数>,"bears":<整数>,"mega":<bool>,"asof":"YYYY-MM-DD"}},
 "equity":{{"price":<数>,"high_52w":<数>,"asof":"YYYY-MM-DD"}},
 "sources":[{{"title":"<来源名>","url":"<真实URL>"}}],
 "note":"<30字内本期要点，只陈述事实不做判断>"}}

硬性要求：所有 url 必须来自本次真实检索，严禁编造；查不到的字段沿用上期值并保持其 asof 不变。"""


def call_model(prev_metrics):
    import anthropic
    cli = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=BASE_URL, timeout=900.0)
    p = PROMPT.format(today=bj_today(), prev=json.dumps(prev_metrics, ensure_ascii=False, indent=1))
    last = ""
    for a in range(1, 4):
        print(f"[信息] 提取指标，第 {a}/3 次 ...")
        try:
            msg = cli.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
                messages=[{"role": "user", "content": p}])
        except Exception as e:
            print(f"[警告] API 异常：{e}"); continue
        searched = any(getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result") for b in msg.content)
        last = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        print(f"[信息] stop={msg.stop_reason} 长度={len(last)} 联网={searched}")
        dec = json.JSONDecoder()
        for mm in re.finditer(r"\{", last):
            try: obj, _ = dec.raw_decode(last[mm.start():])
            except ValueError: continue
            if isinstance(obj, dict) and "spot" in obj and "capex" in obj:
                if not searched and a < 3:
                    print("[信息] 无联网记录，结果不采用，重试"); break
                return obj
        print(f"[警告] 第 {a} 次未解析出指标 JSON")
    sys.exit(f"[错误] 三次均失败。原文前2000字：\n{last[:2000]}")


def main():
    hist = json.load(open(HIST, encoding="utf-8"))
    prev_metrics = hist.get("last_metrics", {})
    ex = call_model(prev_metrics)

    if not [s for s in ex.get("sources", []) if str(s.get("url","")).startswith("http")]:
        sys.exit("[错误] 无真实来源链接，拒绝发布")

    sp = ex["spot"]
    wow = (sp["latest"] / sp["prev"] - 1) * 100 if sp.get("prev") else 0.0
    metrics = [
        {"premium_pct": 120.0, "wow_pct": round(wow, 2), "weeks_down": int(sp.get("weeks_down", 0))},
        ex["capex"], ex["inventory"], ex["demand"], ex["narrative"],
    ]
    # 数据新鲜度：季度指标 asof 未变则视为无增量（分数自然不变，此处仅作标注）
    fresh = {NAMES[i+1]: (ex[k].get("asof") != (prev_metrics.get(k, {}) or {}).get("asof"))
             for i, k in enumerate(["capex", "inventory", "demand", "narrative"])}

    scores = sc.score_all(metrics)
    streak = hist.get("streak_carryover", [0]*5)
    streak = sc.update_streak(streak, scores)
    phase = sc.next_phase(hist.get("last_phase", "扩张期"), scores)
    r = sc.compose(scores, sc.decay_factors(streak), phase)

    wk = hist.get("weekly", [])
    prev_s = wk[-1]["s"] if wk else None
    prev_m = hist.get("last_metrics_mapped")
    b = sc.bottom_score(scores, prev_s, metrics, prev_m) if prev_s and prev_m else {"total": 0}

    eq = sc.equity_anchor(ex["equity"]["price"], ex["equity"]["high_52w"], sp.get("at_record", False))
    today = bj_today()

    entry = {"period": today, "s": scores, "top": r["total"], "bottom": b["total"],
             "phase": phase, "n50": r["n50"], "n75": r["n75"], "trig": bool(r["triggers"]),
             "conf": "high", "kind": "周度实测", "spot": sp["latest"], "wow": round(wow, 2),
             "note": ex.get("note", "")}
    hist["weekly"] = [w for w in wk if w["period"] != today] + [entry]
    hist["streak_carryover"] = streak
    hist["last_phase"] = phase
    hist["last_metrics"] = {k: ex[k] for k in ("capex", "inventory", "demand", "narrative")}
    hist["last_metrics_mapped"] = metrics
    hist["equity_anchor"] = {**ex["equity"], **eq}

    data = {
        "updated": today, "schema": "v3", "top": r["total"], "bottom": b["total"],
        "phase": phase, "stage": r["stage"], "stage_desc": r["stage_desc"],
        "n50": r["n50"], "n75": r["n75"], "triggers": r["triggers"],
        "signals": [{"id": i+1, "name": NAMES[i], "lead": LEADS[i], "score": scores[i],
                     "weight": sc.WEIGHTS[i], "metrics": metrics[i],
                     "fresh": fresh.get(NAMES[i], True)} for i in range(5)],
        "equity_anchor": hist["equity_anchor"],
        "spot": sp, "sources": ex["sources"][:8], "note": ex.get("note", ""),
        "quarterly": hist["quarterly"], "weekly": hist["weekly"],
        "disclaimer": "本页面为个人研究用途的公开信息聚合，由程序按固定规则自动生成，"
                      "季度序列为历史规则重建而非实测，可能存在错误或延迟，不构成任何投资建议。",
    }
    json.dump(hist, open(HIST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    open(OUT, "wb").write(payload)
    print(f"{today}: 五信号={scores} 顶温={r['total']} 底温={b['total']} 相位={phase} "
          f"触发={r['triggers'] or '无'} 股价背离={'是' if eq['alert'] else '否'}")
    upload(payload)


def upload(content: bytes):
    from tencentcloud.common import credential
    from tencentcloud.tcb.v20180608 import tcb_client, models
    from qcloud_cos import CosConfig, CosS3Client
    tcb = tcb_client.TcbClient(credential.Credential(TCB_ID, TCB_KEY), TCB_REGION)
    req = models.DescribeEnvsRequest(); req.EnvId = TCB_ENV
    envs = [e for e in (tcb.DescribeEnvs(req).EnvList or []) if e.EnvId == TCB_ENV]
    if not envs or not envs[0].Storages:
        sys.exit(f"[错误] 未找到环境 {TCB_ENV} 的存储信息")
    st = envs[0].Storages[0]
    CosS3Client(CosConfig(Region=st.Region, SecretId=TCB_ID, SecretKey=TCB_KEY)).put_object(
        Bucket=st.Bucket, Key=CLOUD_PATH, Body=content,
        ContentType="application/json; charset=utf-8", CacheControl="max-age=300")
    print(f"上传成功: https://{st.CdnDomain}/{CLOUD_PATH}")


if __name__ == "__main__":
    main()
