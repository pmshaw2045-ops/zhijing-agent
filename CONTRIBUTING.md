# 贡献指南

感谢你对织镜 ZHÌJÌNG 的关注！欢迎提交 Issue 和 Pull Request。

## 本地开发

### 前置要求

- Python 3.11+
- Node.js 20+（前端测试用）
- 一个 OpenAI 兼容的 LLM API key（DeepSeek / OpenAI 等均可）

### 1. 克隆并安装

```bash
git clone https://github.com/pmshaw2045-ops/zhijing-agent.git
cd zhijing-agent

# 后端
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
pip install -e .                     # 可编辑安装，使模块间相对导入生效

# 前端（可选，仅运行前端测试时需要）
cd frontend && npm install && cd ..
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，至少填入 LLM_API_KEY
```

### 3. 启动

```bash
python3 -m uvicorn backend.server:app --host 0.0.0.0 --port 8899
open http://localhost:8899
```

## 运行测试

```bash
# 后端（核心）
python3 -m pytest tests/ -q --tb=short

# 带覆盖率
python3 -m pytest tests/ --cov=backend --cov-report=term-missing

# 集成测试（需要真实 API key）
USE_REAL_API=1 python3 -m pytest tests/ -m integration

# 前端
cd frontend && npm test
```

## 代码风格

项目使用 **ruff** 做 Python 代码检查。提交前请确保：

```bash
ruff check backend/
ruff format backend/ --check
```

两条规则必须严格遵守：

1. **所有 import 必须在文件顶部**（`logger = logging.getLogger(__name__)` 之前）
2. **相对导入优先**：使用 `from .module import X` 而非 `from module import X`

## 提交规范

commit message 格式：

```
<type>: <简短描述>

- 可选逐条说明
```

type 参考：

| type | 场景 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修 Bug |
| `refactor` | 重构（不改变外部行为） |
| `test` | 增加或修改测试 |
| `docs` | 文档 |
| `chore` | 构建/CI/工具链 |

## Pull Request 流程

1. Fork 仓库并创建你的分支：`git checkout -b feat/your-feature`
2. 提交改动：`git commit -m "feat: 做了什么"`
3. 确保测试通过：`python3 -m pytest tests/ -q && cd frontend && npm test`
4. 推送分支：`git push origin feat/your-feature`
5. 创建 Pull Request，填写模板

## 架构速览

核心流程是 8 阶段 Pipeline：

```
用户输入 → Phase 1 意图识别 → Phase 2 前置校验 → Phase 3 DAG拆解
         → Phase 4-5 工具映射+并行执行 → Phase 6 报告生成 → Phase 7 反思修正
```

详见 [AGENTS.md](AGENTS.md) 了解完整架构。
