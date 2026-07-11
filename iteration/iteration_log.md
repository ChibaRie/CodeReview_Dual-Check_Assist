# 迭代日志

## 2026-07-11 20:00

- 更新类型：feature
- 版本迁移：v0.0 -> v0.1
- 更新摘要：落地 AI 代码评审「双检」MVP，实现静态快检 + AI 语义深检、CQRS 缓存、DeepSeek→Qwen 降级链、熔断器保护和状态机流程。
- 涉及文件：skill/scripts/app.py, circuit_breaker.py, cqrs_router.py, fallback_chain.py, state_machine.py, static_check.py；skill/references/config.example.json；data/sample_*.py, data/sample_go_code.go；tests/test_record.md
- 使用方式：
  - 静态/降级模式：`python skill/scripts/app.py data/sample_buggy_code.py --lang python`
  - 带 AI：`DEEPSEEK_API_KEY=xxx python skill/scripts/app.py data/sample_buggy_code.py --lang python --framework stdlib`
  - JSON 输出：加 `--json`
- 验证结果：
  - `sample_buggy_code.py` 静态-only 返回 7 条 findings，risk=阻止合并
  - `sample_clean_code.py` 返回 2 条 is_literal findings，risk=修复后合并
  - `sample_go_code.go` 非 Python 路径正常返回 2 条正则层 findings，risk=修复后合并
  - 缓存命中：第二次运行约 114.5 ms（首次 159.2 ms），cache 有效
  - `--no-cache` 可强制重新评审
- 后续注意：v0.2 将强化鲁棒性（熔断 cooldown、HALF_OPEN 探针、TTL 清理、更厚的本地兜底），需用真实 API key 跑 AI 路径。
