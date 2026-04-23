"""配置模块测试"""
import pytest


def test_config_import():
    """测试 Config 可以被导入"""
    from config import Config
    assert Config is not None


def test_config_singleton():
    """测试 Config 是单例"""
    from config import Config
    c1 = Config.get()
    c2 = Config.get()
    assert c1 is c2


def test_config_has_watch_list():
    """测试 Config 有 WATCH_LIST"""
    from config import Config
    config = Config.get()
    assert isinstance(config.WATCH_LIST, list)


def test_config_has_data_sources():
    """测试 Config 有 DATA_SOURCES"""
    from config import Config
    config = Config.get()
    assert isinstance(config.DATA_SOURCES, list)


def test_config_has_llm_config():
    """测试 Config 有 LLM 配置"""
    from config import Config
    config = Config.get()
    assert hasattr(config, "LLM_PROVIDER")
    assert hasattr(config, "LLM_API_KEY")
