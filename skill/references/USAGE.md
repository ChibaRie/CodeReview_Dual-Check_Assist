# 双检代码评审助手使用说明

## 功能概述

本工具对代码做“静态快检 + AI 深检”的双层评审。
静态层基于 AST/正则快速发现明显问题；
AI 层基于大模型确认、否定或补充静态层结果。
最终输出合并后的风险等级与问题明细。

## 运行方式

### 1. 文件路径

```bash
python skill/scripts/app.py data/sample_buggy_code.py --lang python
```

### 2. 直接传入代码字符串

```bash
python skill/scripts/app.py --code-string "def f(a=[]): pass" --lang python --json
```

### 3. 标准输入

```bash
cat data/sample_buggy_code.py | python skill/scripts/app.py --lang python
```

## CLI 参数

| 参数            | 必填   | 说明                                      |
|-----------------|--------|-------------------------------------------|
| `code`          | 否     | 待审代码文件路径                          |
| `--code-string` | 否     | 直接传入代码字符串                        |
| `--lang`        | 条件   | 语言，如 `python`、`go`、`javascript`     |
| `--framework`   | 否     | 框架/库上下文，如 `django`、`flask`       |
| `--config`      | 否     | 自定义配置文件路径                        |
| `--no-cache`    | 否     | 跳过缓存                                  |
| `--json`        | 否     | 输出 JSON                                 |

当不提供 `code` 和 `--code-string` 时，工具会运行自检；
否则 `--lang` 必填。

## API 密钥配置

复制 `skill/references/config.example.json` 到项目根目录并按需修改。
模型密钥通过环境变量注入，禁止写入配置文件：

```bash
export DEEPSEEK_API_KEY="sk-..."
export DASHSCOPE_API_KEY="sk-..."
```

支持的环境变量名以配置文件中 `api_key_env` 字段为准。

## 输出解读

- `risk`：风险等级
  - `阻止合并`：存在 high 严重度问题
  - `修复后合并`：仅有 medium/low 问题
  - `可合并`：未发现明显问题
- `findings.layer`：问题来源
  - `static`：静态快检
  - `ai_confirmed`：AI 确认静态层的问题
  - `ai_new`：AI 新发现的问题
- `ai_summary`：AI 层结论；
  若模型链全部失败或熔断器 OPEN，会显示降级说明。

## 降级模式

当熔断器开启或所有模型都不可用时，工具会跳过 AI 深检，
仅输出静态层结果并标记为降级。
此时 `risk` 仍由静态层决定，但建议稍后重试以获得完整语义评审。

## 缓存

默认开启结果缓存，缓存键由代码内容、语言和模型配置共同生成。
相同输入会命中缓存，避免重复调用模型。
使用 `--no-cache` 可跳过读取与写入。
