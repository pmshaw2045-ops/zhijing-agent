.PHONY: test test-integration

# 单元测试（mock LLM，不调真实 API）
test:
	python3 -m pytest

# 集成测试（真实调 DeepSeek API，需要有效密钥）
test-integration:
	USE_REAL_API=1 python3 -m pytest tests/test_integration.py -m integration -v --tb=short
