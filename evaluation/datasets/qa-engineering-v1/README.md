# QA engineering v1

60 条合成工程案例，76 份新建 Markdown 原文。所有案例均为 `model_draft`、`human_reviewed=false`，真实人工复核数为 0；全部放在 `dev`，不符合正式 gold 或发布收益评测条件。

| 类别 | 数量 |
|---|---:|
| 直接事实 | 12 |
| 多段综合 | 8 |
| 资料不足 | 8 |
| 来源冲突 | 8 |
| 指代追问 | 8 |
| 提示注入 | 6 |
| 来源撤权 | 6 |
| 服务失败 | 4 |

`cases.jsonl` 的 `source_refs`、证据组、code-point 范围和 quote hash 来自真实生产解析器。`manifest.json` 固定所有原文与案例文件的 SHA-256。原文没有使用用户业务资料，注入示例中的指令与网址仅为合成文本。

问答样本使用 `question`、同范围的完整 `history=[{question,answer}]`、`expected_answer_status` 和证据组。历史最多 6 对及 8,000 UTF-8 字节，评测入口绑定本次隔离 scope 的 fingerprint。预期技术错误使用 `expected_error_code`，回答状态为 `null` 或省略；技术失败不能算作资料不足。

使用已安装后端锁定依赖的 Python 3.11 环境，在项目根目录运行：

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD\evaluation"
$env:PYTHONUTF8 = '1'
python -m rag_eval.qa_engineering --dataset evaluation/datasets/qa-engineering-v1/manifest.json --workspace .superpowers/qa-v1-validation/qa-recheck-new --output evaluation/reports/qa-v1-recheck
```

`--workspace` 必须是尚不存在的新目录。执行器实际构建不可变索引，调用 `run_eval_sample → RagEngine.answer`，运行 BM25 检索、证据核验、权限检查、生成与支持关系校验。模型替身只能从真实生产提示里的本轮证据提取字段，不读取 gold 或预期状态；网络连接被禁止。`engineering.fault` 仅由这个本地合成执行器解释，普通评测 API 不执行故障注入。

追问包括 6 条改写后重新检索和 2 条指代不明的澄清；多段综合包括 2 条仅有部分依据的回答。提示注入包括安全 framing、历史隔离和对伪造引用、notice 绕过及不支持事实的拒绝。六个撤权边界覆盖开始前、检索后、证据核验后、回答模型返回后、校验模型返回后、最终证据核验后。

`qa_correctness`、`qa_faithfulness` 始终保留 `status=na, reason=not_evaluated`。本地字段提取替身和生产时的支持校验不能提供真实模型质量或校准 Judge 分数。真实模型费用与延迟也保留未知。执行方法、实测结果、首轮索引失败及修复记录见 [QA v1 报告](../../reports/qa-v1.md)。
