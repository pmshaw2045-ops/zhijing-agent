
import sys
import os
import json
import pytest
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# 确保单元测试不依赖真实 API Key（集成测试通过 USE_REAL_API 控制）
if not os.environ.get("USE_REAL_API"):
    os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
    os.environ.setdefault("ARK_API_KEY", "test-key")
    os.environ.setdefault("TAVILY_API_KEY", "test-key")
    os.environ.setdefault("BOCHA_API_KEY", "test-key")


@pytest.fixture
def integration():
    """集成测试标记：需要 USE_REAL_API=1 环境变量"""
    if not os.environ.get("USE_REAL_API"):
        pytest.skip("跳过集成测试（设置 USE_REAL_API=1 执行）")


@pytest.fixture
def sample_json_report():
    """返回一个标准 JSON 报告样本"""
    return json.dumps({
        "title": "法式茶歇裙选品机会分析报告",
        "sections": [
            {"type": "metrics", "data": {"items": [
                {"label": "搜索热度", "value": "82", "accent": "gold"}
            ]}},
            {"type": "bar_chart", "data": {"items": [
                {"label": "¥0-199", "value": 25, "color": "c1", "suffix": "%"}
            ]}},
            {"type": "swot", "data": {
                "brand": "a", "name": "法式茶歇裙",
                "s": ["款式经典"], "w": ["季节性"], "o": ["直播红利"], "t": ["价格战"]
            }},
            {"type": "insight", "data": {"style": "tip", "title": "结论", "body": "值得切入"}}
        ]
    })


@pytest.fixture
def sample_json_str(sample_json_report):
    """返回 JSON 字符串"""
    return sample_json_report
