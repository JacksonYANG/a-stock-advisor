"""策略引擎测试"""
import pytest
from pathlib import Path


def test_strategy_engine_import():
    """测试可以导入"""
    from analyzer.strategy_engine import get_strategy_engine
    assert get_strategy_engine is not None


def test_strategies_dir_exists():
    """测试策略目录存在"""
    strategies_dir = Path(__file__).parent.parent / "strategies"
    assert strategies_dir.exists()
    assert strategies_dir.is_dir()


def test_strategies_are_yaml():
    """测试策略文件都是 YAML"""
    strategies_dir = Path(__file__).parent.parent / "strategies"
    yaml_files = list(strategies_dir.glob("*.yaml"))
    assert len(yaml_files) > 0, "至少应该有一个策略文件"


def test_strategy_yaml_parseable():
    """测试策略 YAML 可以被解析"""
    import yaml
    strategies_dir = Path(__file__).parent.parent / "strategies"
    for yaml_file in strategies_dir.glob("*.yaml"):
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"{yaml_file.name} 不是有效的 YAML dict"
        assert "name" in data, f"{yaml_file.name} 缺少 name 字段"


def test_strategy_signal_dataclass():
    """测试 StrategySignal 数据类"""
    from analyzer.strategy_engine import StrategySignal
    signal = StrategySignal(
        strategy_name="test",
        signal_type="买入",
        strength=0.8,
    )
    assert signal.strategy_name == "test"
    assert signal.signal_type == "买入"
    assert signal.strength == 0.8
