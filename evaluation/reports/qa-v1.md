# QA v1 工程基线

2026-09-09 完成全部 60 条案例的实际执行，**60/60 通过**。76 份原文均为新建合成材料；60 条问题互不相同，均标注 `model_draft`、`human_reviewed=false`，真实人工复核数为 **0**。这份结果证明本地工程机制通过，语义正确性、忠实度及真实模型费用和延迟仍为 **not_evaluated / unknown**。

| 类别 | 实际执行 | 预期行为通过 |
|---|---:|---:|
| 直接事实 | 12 | 12 |
| 多段综合 | 8 | 8 |
| 资料不足 | 8 | 8 |
| 来源冲突 | 8 | 8 |
| 指代追问 | 8 | 8 |
| 提示注入 | 6 | 6 |
| 来源撤权 | 6 | 6 |
| 服务失败 | 4 | 4 |
| 合计 | 60 | 60 |

实际返回 `answered=27`、`partial=2`、`insufficient_evidence=8`、`conflicting_sources=8`、`needs_clarification=2`。另有 13 条按预期技术失败：6 条撤权、4 条服务错误，以及 3 条注入导致的伪造引用、notice 绕过或不支持事实。失败案例均断言没有返回回答块、回答状态、检索改写或来源工件，不能当成拒答成功。

## 实际执行范围

执行路径为 `run_eval_sample → RagEngine.answer → QA pipeline`，没有使用预写回答工件打分。每次运行创建新的隔离 `evaluation:9001` 存储，使用真实解析器、不可变 canonical/span/hash、OwnerIndexStore、Chroma 与 BM25。仅外部 chat/embedding 传输和撤权时钟为确定性替身；模型替身从生产提示中的本轮检索原文提取字段，无法读取 gold、预期状态或评分器。反向测试故意改错预期状态，确认执行器会报告失败。

追问的历史只进入一次改写提示，实际回答重新检索当前范围；两条无法消解指代的案例返回固定澄清。六个撤权点位于开始前、检索后、证据核验后、回答模型返回后、校验模型返回后、最终证据核验后；替身使授权回调返回 false，由生产 `reauthorize_scope` 抛出 `ScopeRevoked`。四类服务故障为超时、429、截断 JSON 和缺 provider。注入测试核对不可信数据 framing、历史隔离，以及真实引用/notice/支持检查的拒绝行为。

每条结果保存实际工件、状态、权限/检索/模型调用观测和独立断言，检查逐块引用身份、授权来源、原文 hash/locator、事实引用覆盖、已引用证据组命中、最多一次检索和最多五次模型调用。整个运行观察到 103 次本地替身 chat 调用、0 次网络尝试、0 次真实模型调用。运行没有学习持久化端口，且逐条断言没有调用 quiz/learning 生成入口；SQL/API/lease/浏览器的集成验收由项目其他测试单独记录。

QA 的确定性指标为 `qa_answer_status_match`、`qa_answer_structure_validity`、`qa_citation_validity`、`qa_fact_citation_coverage`、`qa_evidence_group_recall`、`qa_all_evidence_hit`、`qa_failure_behavior_match`。`qa_correctness` 与 `qa_faithfulness` 均保留 `status=na, reason=not_evaluated`，即便生产期语义检查通过或输入声称 Judge 已校准，也不输出语义质量分数。QA 不继承 quiz Judge 的校准标志，一般用户评价也不视为完成语义人审。

## 首轮失败与修复

首轮确实执行了 60 条，仅 34 条通过。26 条正常案例在模型调用前出现 `SOURCE_UNAVAILABLE`。诊断定位为 Chroma 1.5.9 的 `collection.get(include=['embeddings'])` 报 `Error creating hnsw segment reader: Nothing found on disk`：小型不可变集合未达到默认 1000 向量同步阈值，同一 owner 后续重载 segment 时没有已物化文件。重开索引可读，不代表原错误已消失。

回归测试在同一 owner 创建 36 份小索引后读取两遍，修复前捕获 18 次该错误。建集合改用显式 HNSW 配置，batch/sync threshold 均为 `min(100, child_count)`；空 child 原有拒绝分支保留，较大索引仍按 100 批大小，并增加 116 节点、末批未满的检查。原文、checksum、向量身份/维度、docstore、词法索引和权限检查均保留，没有跳过验证或添加隐藏重试。

修复后在全新存储实际重跑全部 60 条，得到 60/60；最终格式整理改变源码指纹后，又以固定后的最终代码完整重跑 60/60。本报告对应最后一次实际执行，代码指纹已重新与当前源码核对。首轮完整结果及原始校验和保存在 [initial-run](qa-v1/initial-run/summary.json)；最终结果见 [summary.json](qa-v1/summary.json)、[results.jsonl](qa-v1/results.jsonl)、[checksums.json](qa-v1/checksums.json) 和 [audit.json](qa-v1/audit.json)。

## 运行与验证

实际使用 Windows、Python 3.11.15 及后端锁定依赖。全量本地墙钟时间为 99.185 秒，包含建索引与替身执行；它不是实际模型或生产用户延迟。实际命令的 Python 绝对路径与完整参数保存在 `summary.json.command`。

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD\evaluation"
$env:PYTHONUTF8 = '1'
python -m rag_eval.qa_engineering --dataset evaluation/datasets/qa-engineering-v1/manifest.json --workspace .superpowers/qa-v1-validation/t05-baseline-03 --output evaluation/reports/qa-v1
```

重新执行须替换为尚不存在的 `--workspace`，可另设输出目录以保留当前报告。

| 检查 | 实际结果 |
|---|---|
| QA 评测、执行器、常规费用、索引/检索/来源生命周期受影响后端回归 | 79 passed；1 个数据库测试有意留给主集成验收 |
| 独立 evaluation 全 core | 190 passed，26 skipped |
| 最终独立 Ragas 环境全回归（主任务复核） | 216 passed，无跳过；模型传输为本地替身 |
| 60 条生产管线工程案例 | 60 passed，退出码 0 |
| 独立复查的 backend QA evaluation 测试 | 24 passed |
| 独立复查的 QA/metrics/datasets 纯测试 | 79 passed |
| Ruff 与 git diff --check | 通过 |

core 环境的 26 条跳过均要求独立 `requirements-ragas.lock` 环境；主任务在该隔离环境运行了全部 216 项并通过，包含真实 SDK/Ragas 接口与本地模型传输。没有调用真实服务商或测量 Judge 质量。后端回归有一个已存在的 Pydantic 字段元数据告警。测试命令与红/绿日志另保存在 `.superpowers/qa-v1-validation/t05-*.txt` 和 `t06-eval-*.txt`。

```text
cd backend
python -m pytest tests/rag/test_small_index_persistence.py tests/rag/test_hybrid_retrieval.py tests/rag/test_source_lifecycle.py tests/rag/test_llamaindex_adapter.py tests/rag/test_scope_policy.py tests/qa/test_evaluation.py tests/qa/test_engineering_runner.py tests/rag/test_evaluation_facade.py tests/platform/test_evaluation_cost_preview.py -k "not test_preview_is_owner_scoped" -q --tb=short --basetemp=<new-workspace-temp>

cd evaluation
python -m pytest tests -m "not external" -q --tb=short --basetemp=<new-workspace-temp>
```

## 数据与结果校验和

已核对全部 77 份数据文件（76 原文 + cases）、60 个工件 hash 和结果文件。数据集维持 draft，不可冻结成无人审正式 gold。

| 对象 | SHA-256 |
|---|---|
| 数据集 manifest | `731b6c059dc31056d8175b161dafdd5a10e51b45570bc53b52f2949cb5da439c` |
| cases.jsonl | `6edc5ba8ab48c0de755bd403ab17ca1e6ed39364ef7da2965a501a227b59240a` |
| 已加载数据集内容 | `cea4a92375bdf0e25eca00c714da6b821a7899dd5fe3443cb0bdabff29f380d3` |
| 最终 results.jsonl | `2d31997e63ed27ca5478c69362cb2d9791e3be18ebb127f9ea414cc4ffae83a1` |
| 最终 summary.json | `8fc42c1124c03a8b7f00a8b6381cc02c5404f4352c12fa532e706b264996ad0b` |
| 执行代码指纹 | `f873f0f97072b8efdcfe7cf026c775dd6fa8e8ae162d0922bb7f648b77ff73e3` |

真实 Claude 回答、重排、语义校验、prompt injection 抵抗能力、费用与延迟没有被这份合成结果测量；没有更换服务来生成这些值。人工正确性/忠实度验收、人类 gold 和任何学习效果收益均未进行或声称。
