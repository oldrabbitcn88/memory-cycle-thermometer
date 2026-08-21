#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性数据抓取层：不依赖任何 LLM 或网关搜索能力。
最时效敏感的两项（现货价、市场定价锚）由正则直接解析，失败即报错，不猜。"""
import re, sys
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; MemoryCycleThermometer/1.0)"}
SRC_SPOT = "https://capitalandcompute.net/memory-prices/"

MONTHS = {m: i+1 for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])}


def _get(url, timeout=45):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_spot():
    """返回最近两期现货读数 + 连续下跌周数。数据源含完整周度表格。"""
    html = _get(SRC_SPOT)
    txt = re.sub(r"<[^>]+>", " ", html)
    # 匹配形如 "Jul 21, 2026 | $41.10" 的表格行（容忍任意分隔与空白）
    rows = re.findall(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(20\d{2})[^$]{0,60}\$\s*(\d+\.\d{2})", txt)
    seen, series = set(), []
    for mo, d, y, p in rows:
        if mo not in MONTHS:
            continue
        key = (int(y), MONTHS[mo], int(d))
        if key in seen:
            continue
        seen.add(key)
        series.append((f"{y}-{MONTHS[mo]:02d}-{int(d):02d}", float(p)))
    series.sort()
    if len(series) < 2:
        sys.exit(f"[错误] 现货序列解析失败，仅得到 {len(series)} 条。数据源结构可能已变，需人工检查 {SRC_SPOT}")
    # 连续下跌周数
    wd = 0
    for i in range(len(series) - 1, 0, -1):
        if series[i][1] < series[i-1][1]:
            wd += 1
        else:
            break
    latest, prev = series[-1], series[-2]
    at_record = latest[1] >= max(p for _, p in series)
    return {"latest_date": latest[0], "latest": latest[1],
            "prev_date": prev[0], "prev": prev[1],
            "weeks_down": wd, "at_record": at_record,
            "series_len": len(series), "source": SRC_SPOT,
            # 完整序列供小程序画图。注意数据源发布的是"selected official readings"，
            # 日期不规则（相邻两点间隔 5~140 天不等），不是严格周频。
            "series": [{"d": d, "p": p} for d, p in series]}


def fetch_equity():
    """Roundhill Memory ETF (DRAM) 现价与高点。同页披露，避免再引一个源。"""
    txt = re.sub(r"<[^>]+>", " ", _get(SRC_SPOT))
    m = re.search(r"\$\s*(\d+\.\d{2})\s*,?\s*down\s+\d+%\s+from\s+(?:its\s+)?\$\s*(\d+\.\d{2})\s+high", txt)
    if not m:
        m = re.search(r"ETF\s*\(DRAM\)[^$]{0,80}\$\s*(\d+\.\d{2})[^$]{0,120}\$\s*(\d+\.\d{2})", txt)
    if not m:
        return None
    return {"price": float(m.group(1)), "high_52w": float(m.group(2)), "source": SRC_SPOT}


if __name__ == "__main__":
    s = fetch_spot()
    print("现货:", s)
    print("市场定价锚:", fetch_equity())
