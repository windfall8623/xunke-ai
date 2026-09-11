export function SampleTypeHelp() {
  return (
    <details className="technical-details">
      <summary>支持的样本类型与新题型字段</summary>
      <p className="tiny muted">
        支持检索、出题、策略、问答、练习生成和答案判分；原有样本可继续导入。
      </p>
      <p className="tiny muted">
        练习生成使用 <code>case_type: practice_generation</code>：在 <code>spec</code> 中保留
        目标、概念、题型和题量，题型为 <code>cloze</code>（填空）、<code>numeric</code>（数值）或
        <code>short_answer</code>（简答）。<code>expected_outcome</code> 声明生成、拒绝或失败；
        失败样本同时保留 <code>expected_error_code</code>。
      </p>
      <p className="tiny muted">
        答案判分使用 <code>case_type: answer_grading</code>：保留完整的 <code>question</code>、
        <code>answer</code>、<code>question_type</code> 和原始题目、规则、作答 hash。
        <code>reference_grade</code> 是独立参考，分数使用 0–1 的十进制字符串；未知分数保留
        <code>null</code>，不填零。工程夹具与人工参考分别标注来源。
      </p>
      <p className="tiny muted">
        两种新样本都需要已授权的 <code>source_refs</code>、文档家族与 split。
        导入时由服务端校验完整契约；独立参考不会传给被测判分器。
      </p>
    </details>
  )
}
