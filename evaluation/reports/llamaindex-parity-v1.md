# B1 LlamaIndex 迁移对照：待运行说明

日期：2026-09-08。**真实模型 B1 尚未运行，本文件不包含真实等价性、非劣性或质量提升结论。** 本地工程测试覆盖显式 Embedding、固定向量/文本、授权过滤及原文身份；实际结果入口见 [实施记录](../../docs/web-rag-implementation-status.md)，相关用例见 [dense parity](../../backend/tests/rag/test_dense_parity.py) 和 [LlamaIndex adapter](../../backend/tests/rag/test_llamaindex_adapter.py)。

## 比较对象与控制变量

使用 `legacy-dense-v1` 对 `llamaindex-dense-v1`。当前 `dense-v1` 在 [评测配置解析](../../backend/app/services/evaluation_service.py) 中映射为 `llamaindex-dense-v1`，因此不能用这两个别名的自对照声称完成框架迁移验证。历史摘要/截断 `legacy-summary-b0` 属于 B0，另作旧方案基线，不与纯检索适配器的单因素 B1 混写。

两边固定相同授权资料、原文件与 parse hash、分块及原文 span、Embedding endpoint/model/维度、实际输入文本、query、scope、top-k、上下文预算和样本集合。保留实际索引 build/attempt 和运行 manifest；并列分数按预先约定规则处理。不能因某次分数不理想而更换样本、切块或 Embedding。

## 启动真实对照前

- 完成可用授权 pilot 的真实人工标注、复核和冻结；固定 dev/calibration/locked-test 的家族/连通簇划分。
- 配置真实 Embedding、生成服务、价格及有限预算，记录模型版本不可固定等实际限制。
- 事先固定数值容忍、并列顺序和等价/非劣判断协议，保留协议 hash；不要查看 locked-test 结果后放宽门槛。
- 在网页评测工作台分别创建两种注册方案的运行，使用相同冻结版本、重复次数与评分协议；原文撤权后不得继续使用旧授权。

## 待填结果

| 字段                                             | 当前记录                           |
| ------------------------------------------------ | ---------------------------------- |
| 两个真实运行 ID / manifest hash                  | 未运行                             |
| 数据集冻结版本 / source / parse / build          | 未登记真实对照输入                 |
| 实际模型、输入、向量维度和价格                   | 未登记真实对照配置                 |
| 相同 query/scope 的候选 ID、排名、并列及数值偏差 | 未测量                             |
| 原文 span/quote hash、owner/scope 和重启可读性   | 有工程回归；真实部署对照结果待记录 |
| coverage、失败/unknown、评分覆盖、费用与延迟     | 未测量真实对照                     |
| 预设协议、样本/独立簇数、区间和结论              | 未形成真实验收结论                 |

B1 可以证明框架迁移等价或非劣，不要求带来质量提升；任何不等价结果必须保留原因、原始工件和实际配置。完成后将真实运行、导出、失败分析与判断写入本报告，并关联 [工程发布记录](release-v1.md)。未达到协议的方案保持实验或回退状态。
