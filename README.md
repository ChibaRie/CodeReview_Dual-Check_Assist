# AI 代码评审「双检」助手

> 静态规则快检 + AI 语义深检，让独立开发者也能拥有稳定可靠的代码 Review。

## 核心能力

- **双检**：静态层抓表面问题，AI 层解释告警并发现逻辑 Bug。
- **CQRS 缓存**：重复评审同段代码，第二次毫秒级返回。
- **模型降级链**：DeepSeek 失败自动切 Qwen，均失败则基于静态结果给出最小说明。
- **熔断器**：AI 子系统异常时退化为纯静态报告，不挂掉。

## 快速开始

```bash
# 1. 设置 API 密钥（通过环境变量，禁止写入配置文件）
export DEEPSEEK_API_KEY=your_key
# 可选：export DASHSCOPE_API_KEY=your_key

# 2. 评审一个文件
python skill/scripts/app.py data/sample_buggy_code.py --lang python

# 3. JSON 输出
python skill/scripts/app.py data/sample_buggy_code.py --lang python --json
```

## 项目结构

- `skill/scripts/`：六个核心脚本，每个 <200 行
- `skill/references/`：配置示例、使用说明、最佳实践
- `data/`：测试语料
- `tests/test_record.md`：回归基线
- `iteration/iteration_log.md`：迭代记录

## 迭代路线

- v0.1：双检并行 MVP（当前）
- v0.2：鲁棒性强化（熔断 cooldown、TTL 清理、更厚兜底）
- v0.3：多语言扩展 + 输出优化 + 沉淀 SKILL.md

详见 `iteration/iteration_log.md` 与 `docs/superpowers/specs/2026-07-11-dual-check-design.md`。
