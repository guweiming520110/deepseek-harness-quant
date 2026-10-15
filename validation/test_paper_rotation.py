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
