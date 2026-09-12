# 工程基线验证记录

日期：2026-09-07。范围：本地 Python 3.11、合成资料、确定性指标与假模型服务。**真实模型 B0 / dense / LlamaIndex 优劣尚未评测；本报告不声称 RAG 质量提升。**

## 已实际执行的离线流程

| 输入 | 样本数 | 资料 / 家族 | 独立连通簇 | 实际人工复核 | 可冻结 |
|---|---:|---:|---:|---:|---|
| smoke 草稿 | 30 retrieval + 10 quiz + 6 policy = 46 | 4 / 4 | 2 | 0 | 否 |
| pilot 草稿 | 150 retrieval + 30 quiz = 180 | 20 / 20 | 20 | 0 | 否 |

实际 CLI 校验输出保存在 [smoke-validation.json](smoke-validation.json) 与 [pilot-draft-validation.json](pilot-draft-validation.json)。两份输入合法且含真实合成原文/span，但均为 draft，不符合人工 gold 冻结条件。

CLI 已对 46 个预先保存的合成工件完成确定性评分，输出 [smoke-results.jsonl](smoke-results.jsonl) 与 [smoke-run.json](smoke-run.json)。这是离线评估，external_model_calls=0；没有执行真实模型生成或记录真实供应商账单。

将同一份 smoke 输出与自身比较，得到 [JSON 比较记录](smoke-self-comparison.json) 和 [Markdown 对照](smoke-self-comparison.md)。2026-09-08 已按最终费用门槛重新生成。结论为 exploratory，comparison_eligible=false；限制包括草稿未人工冻结、独立锁定簇不足、judge 未校准、split 不是单一 locked_test、正式协议未冻结、费用/冻结预算不满足正式资格。46 个请求只有 2 个独立连通簇，不能以请求数量替代独立样本量。

## Ragas 可运行性与历史基线保存

实际隔离环境安装 Ragas 0.4.3 + langchain-community 0.4.1，并调用 collections.Faithfulness.ascore 的真实接口；测试中的模型传输使用本地假服务，不访问模型供应商。当前实际提示词 hash 为 `06e07e3496e5388dcd774a3b26c632742c1d4a86bc1fc08d662bec989e5de12e`，本地检查结果见 [ragas-runtime-info.json](ragas-runtime-info.json)。该检查 model_calls=0，不等于 judge 已经校准。

历史源码快照为 [source-7302ad2.tar.gz](../baselines/source-7302ad2.tar.gz)，清单为 [legacy-b0.json](../baselines/legacy-b0.json)。源码 commit 为 `7302ad2a4b16155762017b7020122ee787decbac`，归档 SHA-256 为 `14123179792d55fe7e19c8d9ad9589f8ae1f02ca6171df8e077a77eeea04109b`。B0 adapter 会校验快照再使用原摘要/截断路径；它的存在不表示已经完成真实 pilot 对照。

后端集成覆盖真实 MySQL、单 owner Chroma 和独立 scorer 的 HTTP 领取/心跳/提交；外部模型均使用可控测试服务。费用超时保留未知预留、旧 lease 禁止覆盖、人工复核保留自动指标、反馈副本和删除级联都有自动化测试。具体最新测试计数以项目最终验收记录为准。

## 尚需真实验收的结果

1. 对真实或明确授权的 pilot 来源完成逐例标注、题量充分性判断、第二人复核和冻结。
2. 配置真实 provider、定价和预算，运行 B0 与 dense / LlamaIndex；保存工件、usage、失败和不确定项。
3. 用 judge_calibration 集进行真实人工 / judge 校准，记录误接受、误拒绝及人工批准；再锁定判定协议。
4. 在独立 locked_test 上进行配对簇比较；测量真实 p50/p95、生成成本、有效题产出和来源质量。样本不足时只作探索结论。
5. 完成生产数据迁移、备份恢复与目标部署环境验证。合成回归与 Docker 可启动检查不能替代这些外部验收。
