"""data/fetch_index_daily.py — 基准指数日线增量更新（Regime 择时数据源）

Regime 择时基于沪深300 日线（bars.db SH.000300）。本脚本每日收盘后增量拉取
最近 N 个交易日数据入库，确保择时信号使用到最新收盘价。

用法：
  python data/fetch_index_daily.py              # 增量拉取（默认最近 15 个交易日）
  python data/fetch_index_daily.py --days 60    # 拉取 60 天（补缺口）
  python data/fetch_index_daily.py --days 2000  # 回补历史（自动分段，见 ★2026-10-16）

★2026-10-16 分段拉取：baostock 单次拉大范围（如 2000 天）会报 "10002007 网络接收错误"
  → 按 --chunk（默认 250 交易日 ≈ 400 自然日）逐段回溯，段间幂等 upsert。
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(k, None)

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from data.cache import DailyCache  # noqa: E402  （需先注入 BASE 到 sys.path）
from data.fetcher_baostock import fetch_daily  # noqa: E402

INDEX_CODES = ["sh.000300"]          # 沪深300（Regime 基准）
CODE_ALIAS = {"sh.000300": "SH.000300"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=15, help="拉取最近 N 个交易日")
    ap.add_argument("--chunk", type=int, default=250,
                    help="分段大小（交易日；baostock 单次大范围易网络超时）")
    args = ap.parse_args()

    cache = DailyCache()

    for code in INDEX_CODES:
        # ★2026-10-16 分段回溯：单次 8 年拉取会 "10002007 网络接收错误"，按 chunk 逐段拉。
        remain = args.days
        cur_end = datetime.now()
        total = 0
        failed = 0
        while remain > 0:
            n = min(args.chunk, remain)
            span = int(n * 1.6) + 5          # 交易日 → 自然日（含周末/节假日冗余）
            seg_start = (cur_end - timedelta(days=span)).strftime("%Y-%m-%d")
            seg_end = cur_end.strftime("%Y-%m-%d")
            try:
                df = fetch_daily(code, start_date=seg_start, end_date=seg_end, adjust="none")
                if df is not None and not df.empty:
                    total += cache.put_daily(CODE_ALIAS[code], df, adjust="none", source="baostock")
            except Exception as e:
                # ★baostock 服务端不稳定（实测 10002007 网络接收错误）→ 单段失败不中断；
                #   upsert 幂等，重跑本命令即可逐步续拉补齐。
                failed += 1
                print(f"  ⚠ {seg_start}~{seg_end} 失败（{str(e)[:50]}）→ 跳过，可重跑续拉")
            cur_end = cur_end - timedelta(days=span)
            remain -= n
            time.sleep(0.5)              # 段间轻微延迟，降低 baostock 瞬时压力
        rng = cache.get_meta(CODE_ALIAS[code], "none") or {}
        print(f"{code}: 写入 {total} 行（失败段 {failed}）→ "
              f"{rng.get('start_date')} ~ {rng.get('end_date')} 累计 {rng.get('rows')} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
