"""测试 config.py — 配置加载 + 优先级验证"""
import os
import pytest

# 必须在 import config 前覆盖环境变量
os.environ["DEEPSEEK_API_KEY"] = "test-key-ds"
os.environ["ARK_API_KEY"] = "test-key-ark"
os.environ["TAVILY_API_KEY"] = "test-key-tv"
os.environ["BOCHA_API_KEY"] = "test-key-bc"
os.environ["APP_ENV"] = "test"

# 重新加载模块以应用新环境变量
import importlib, config
importlib.reload(config)

from config import (
    DEEPSEEK_API_KEY, ARK_API_KEY, TAVILY_API_KEY, BOCHA_API_KEY,
    APP_ENV, IS_PROD, diagnostics,
    LLM_API_KEY, LLM_MODEL_FLASH, LLM_MODEL_PRO, LLM_MODEL_CHAT,
)


def test_config_loaded_from_env():
    """从环境变量加载密钥"""
    assert DEEPSEEK_API_KEY == "test-key-ds"
    assert ARK_API_KEY == "test-key-ark"
    assert TAVILY_API_KEY == "test-key-tv"
    assert BOCHA_API_KEY == "test-key-bc"


def test_app_env():
    """APP_ENV"""
    assert APP_ENV == "test"
    assert IS_PROD is False  # test != production


def test_diagnostics_struct():
    """诊断函数返回正确结构"""
    d = diagnostics()
    assert "env" in d
    assert "is_prod" in d
    assert "llm" in d
    assert isinstance(d["llm"], bool)
    assert "llm_models" in d
    assert "flash" in d["llm_models"]
    assert "search_provider" in d


def test_llm_api_key_backward_compat():
    """DEEPSEEK_API_KEY 作为向后兼容别名"""
    assert LLM_API_KEY == "test-key-ds"
    assert DEEPSEEK_API_KEY == LLM_API_KEY


def test_model_config():
    """模型配置默认值"""
    assert LLM_MODEL_FLASH == "deepseek-chat"
    assert LLM_MODEL_PRO == "deepseek-v4-pro"
    assert LLM_MODEL_CHAT == "deepseek-chat"
