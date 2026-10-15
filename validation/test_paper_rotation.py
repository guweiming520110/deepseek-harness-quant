"""validation/test_paper_rotation.py — 纸上短线轮换引擎测试（TDD）

对应实施计划 docs/plans/2026-10-16-paper-rotation.md
设计文档 docs/plans/2026-10-16-paper-rotation-design.md
"""
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent


def _cfg():
    return yaml.safe_load((BASE / "config" / "params.yaml").read_text(encoding="utf-8"))


def test_config_paper_rotation_present_and_defaults():
    pr = _cfg().get("paper_rotation")
    assert isinstance(pr, dict)
    assert pr["enabled"] is False            # 默认关闭，需显式开启
    assert pr["account_name"] == "rotation"  # 独立账户，不碰 default
    assert pr["initial_cash"] == 1000000
    assert pr["max_positions"] == 6
    assert pr["max_weight_per_stock"] == 0.25
    assert pr["top_n_buy"] == 3
    assert pr["exit_rank_threshold"] == 10
    assert pr["min_hold_days"] == 3
    assert pr["max_hold_days"] == 20
    assert pr["execution"] == "next_open"


def test_config_example_has_same_keys():
    a = _cfg()["paper_rotation"].keys()
    b = yaml.safe_load((BASE / "config" / "params.yaml.example")
                       .read_text(encoding="utf-8"))["paper_rotation"].keys()
    assert set(a) == set(b)


def test_load_rotation_cfg_defaults_when_missing(tmp_path):
    import strategy.paper_rotation as pr
    cfg = pr.load_rotation_cfg(path=tmp_path / "nonexistent.yaml")
    assert cfg["max_positions"] == 6 and cfg["enabled"] is False   # 缺省兜底不崩


def test_load_shortline_scores_parses_entries():
    import strategy.paper_rotation as pr
    scores = pr.load_shortline_scores()          # 读 logs/tech_pitch_*.json（取 mtime 最新）
    assert isinstance(scores, dict)              # {code: {"score", "name", ...}}
    for code, v in scores.items():
        assert isinstance(code, str) and code.count(".") == 1
        assert isinstance(v["score"], (int, float))
    # 文件不存在时必须返回空 dict（不抛异常）
    assert pr.load_shortline_scores(pattern="logs/__no_such__*.json") == {}
