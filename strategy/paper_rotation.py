"""纸上短线轮换引擎（设计见 docs/plans/2026-10-16-paper-rotation-design.md）

职责：读短线分数 → 算买卖清单 → 写 pending → 次日开盘价撮合（无前视偏差）。
记账一律走 PaperAccount（account 由配置决定，默认 'rotation'，绝不碰 default）。
"""
import glob
import json
import os
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
