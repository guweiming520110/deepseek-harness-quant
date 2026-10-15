"""纸上短线轮换引擎（设计见 docs/plans/2026-10-16-paper-rotation-design.md）

职责：读短线分数 → 算买卖清单 → 写 pending → 次日开盘价撮合（无前视偏差）。
记账一律走 PaperAccount（account 由配置决定，默认 'rotation'，绝不碰 default）。
"""
import glob
import json
import os
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "enabled": False, "account_name": "rotation", "initial_cash": 1000000,
    "max_positions": 6, "max_weight_per_stock": 0.25, "top_n_buy": 3,
    "exit_rank_threshold": 10, "min_hold_days": 3, "max_hold_days": 20,
    "execution": "next_open", "tech_source": "logs/tech_pitch_*.json",
}


def load_rotation_cfg(path=None) -> dict:
    """读 config/params.yaml 的 paper_rotation 段；文件缺失/字段缺失 → 用 DEFAULTS 兜底"""
    cfg = dict(DEFAULTS)
    p = Path(path) if path else BASE / "config" / "params.yaml"
    try:
        import yaml
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        seg = raw.get("paper_rotation") or {}
        cfg.update({k: v for k, v in seg.items() if v is not None})
    except Exception as e:
        print(f"[paper_rotation] 读配置失败，用默认：{str(e)[:60]}")
    return cfg


def _latest_glob(pattern: str):
    """按 mtime 取最新的匹配文件（项目铁律：Deck glob 必须按 mtime）"""
    fs = sorted(glob.glob(str(BASE / pattern)), key=os.path.getmtime)
    return Path(fs[-1]) if fs else None


def load_shortline_scores(pattern: str = "logs/tech_pitch_*.json") -> dict:
    """短线分数 {code: {score, name, horizon_days}}；无产物 → {}（不抛异常）"""
    f = _latest_glob(pattern)
    if f is None:
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for e in (d.get("entries") or []):
        code = e.get("code")
        if not code:
            continue
        out[code] = {"score": float(e.get("score") or 0.0),
                     "name": e.get("name") or code,
                     "horizon_days": 20}
    return out


PAPER_DB = BASE / "data" / "cache" / "paper.db"

_PENDING_DDL = """
CREATE TABLE IF NOT EXISTS rotation_pending (
  signal_date TEXT NOT NULL, exec_date TEXT NOT NULL,
  code TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL,
  reason TEXT, created_at TEXT,
  PRIMARY KEY (signal_date, code, side)
);
"""


def ensure_pending_table(db_path=None) -> None:
    """建 pending 表（幂等；与 PaperAccount 同库不同表，不改其 schema）"""
    p = Path(db_path or PAPER_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    try:
        con.execute(_PENDING_DDL)
        con.commit()
    finally:
        con.close()


def write_pending(db_path, signal_date: str, exec_date: str, orders: list) -> int:
    """写入待执行订单（T-1 出单、T 日开盘撑合）；同主键覆盖，幂等重跑安全"""
    import datetime as _dt
    con = sqlite3.connect(str(db_path))
    try:
        con.executemany(
            "INSERT OR REPLACE INTO rotation_pending "
            "(signal_date, exec_date, code, side, qty, reason, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [(signal_date, exec_date, o["code"], o["side"], int(o["qty"]),
              o.get("reason", ""),
              _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")) for o in orders])
        con.commit()
    finally:
        con.close()
    return len(orders)


def load_pending(db_path, exec_date: str) -> list:
    """读某成交日的待执行订单（side DESC → sell 在前，先卖后买）"""
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "SELECT code, side, qty, reason FROM rotation_pending WHERE exec_date=? "
            "ORDER BY side DESC, code", (exec_date,))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        con.close()


def is_limit_locked(bar: dict) -> bool:
    """一字板（开盘即封死）：open==high==low 且偏离前收 ≥9.8%（含 10%/20% 板块近似）
    任一字段缺失 → 视为非一字板（保守，不拦单）"""
    o, h, low, pc = (float(bar.get(k) or 0)
                     for k in ("open", "high", "low", "preclose"))
    if not (o and h and low and pc):
        return False
    return abs(o - h) < 1e-9 and abs(o - low) < 1e-9 and abs(o / pc - 1) >= 0.098


def compute_sells(holds: list, scores: dict, cfg: dict, ranked_codes: list) -> dict:
    """4 级优先级卖出：stop > time_stop > rank_decay
    （第 4 级「替换式轮动」满仓时由调用方在 compute_buys 前补齐）

    ranked_codes：短线分数降序的 code 列表（前 exit_rank_threshold 名视为仍在榜）
    返回 {"sells": [{"code","reason","qty"}], "kept": [...]}
    """
    top_set = set(ranked_codes[:int(cfg["exit_rank_threshold"])])
    min_hold = int(cfg["min_hold_days"])
    max_hold = int(cfg["max_hold_days"])
    sells, kept = [], []
    for h in holds:
        code = h["code"]
        days = int(h.get("hold_days") or 0)
        plan = h.get("stop_plan") or {}
        last, cost = h.get("last_price"), h.get("entry_price")
        ret = None
        if last is not None and cost:
            ret = float(last) / float(cost) - 1
        reason = None
        # 1) 止损（不受最小持有期约束 —— 风险优先）
        sl = plan.get("stop_loss_pct")
        if sl and ret is not None and ret <= -abs(float(sl)):
            reason = "stop"
        # 2) 时间止损
        elif days > max_hold:
            reason = "time_stop"
        # 3/4) 分数衰减（须满足最小持有期）
        elif days >= min_hold and code not in top_set:
            reason = "rank_decay"
        if reason:
            sells.append({"code": code, "reason": reason, "qty": h.get("qty", 0)})
        else:
            kept.append(h)
    return {"sells": sells, "kept": kept}
