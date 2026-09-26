## 兼容扩展（2026-09-19）

沿用 SQLite 中 JSON 正文和 revisions 表，无生产迁移。新字段均为兼容性扩展：`source_snapshot` 保留清洗前的结构化原始提取，已有记录保存时不可替换；`processing_status` 与 `review_status` 区分处理完成度和内容审核；`source_evidence` 单独保存原页/原件参考；任务 `coverage.total_questions=null` 表示总数未知。

`figure_records` 使用 `figure_id`、`position`、内容哈希与基线修订绑定图槽，原裁图与 SVG 分别记录状态；候选核验留在 `figure_review_attempt`，不移植到旧图。`prefix_cleaning` 保存规则版本、原字段快照、前后哈希、移除的明确元数据；正文已修改时阻止旧清洗撤销覆盖。相似题忽略以双方内容指纹为键，只作提醒不合并。

# 统一内容模型 1.0

权威数据为SQLite中保存的有版本JSON，非HTML、编辑器临时JSON或DOCX。`backend/model.py`为可执行Pydantic定义；模型最终响应的JSON Schema由此生成，禁止未知字段。

## 内容

Span：`{kind: "text" | "math", text: string}`。math的text为LaTeX。

Block：必含 `kind, spans, latex, rows, shapes, asset`。不适用字段取空字符串/数组。

- paragraph：spans混合文字与行内公式。
- equation：latex独立公式。
- table：rows[row][column][span]，真实矩形表格；单元格也可含公式。
- geometry：shapes是point/line/circle/label数组；每个对象含kind、x、y、x2、y2、radius、label。
- image：asset必须引用原材料现有素材；不支持重建时保留且阻止当前导出，不静默变图片。

## 模型解析结果

`ParseResult = {schema_version:"1.0", questions: Extracted[]}`。

Extracted含 original_number、subject、grade、question_type、knowledge[]、difficulty、stem[]、options[{label,blocks}]、subquestions[{label,blocks}]、original_answer[]、original_explanation[]、ai_answer[]、ai_explanation[]、pitfalls[]、issues[]、pages[]。

pages为提供的物理页码子集；纯文字、图片、DOCX无可靠物理页码时为[]。人工来源信息不由模型编造。

## 持久化题目

在Extracted上增加 id、revision、schema_version、created_at、updated_at、human_answer[]、human_explanation[]、answer_edited、explanation_edited、answer_is_complete（兼容早期合并答案）、review_status、answer_status、source、provider_info、geometry_status。

source含原材料sha256 id、实际副本文件名、pages、region（未定位时null）。provider_info记录provider、可获得的model、seconds、tokens、cost；未提供的值不估算。

review_status只允许pending/approved；AI入库始终pending。修改stem/options/subquestions会重置审核与答案状态。保存带revision进行并发冲突检查，每次成功保存写入revisions表。

## 编辑界面到模型的映射

界面只显示“题目”“AI答案”“AI解析”。题目将原stem、options、subquestions连续呈现，首次正文修改后收敛到stem（options/subquestions置空，原结构保留在历史修订中）。选择题选项依然是题目内容，不需分块编辑。

AI答案/解析可人工编辑：新内容分别保存为human_answer/human_explanation覆盖层，edited标志保证用户明确清空内容时不会意外回退旧AI文本。原ai_answer/ai_explanation仍保留，不伪称修改后的内容来自模型。导出采用有效覆盖层；学生版不读取这些字段。

Tiptap paragraph、inlineMath、displayMath、table和geometry节点与上述结构确定性互转，不把Tiptap JSON设为权威数据。前端不暴露添加复杂内容的常驻工具栏。

## 任务与快照

Task含id、key、status、bundle、created_at、pid、error、question_ids、meta。status：queued/running/succeeded/failed/cancelled/interrupted。重启时无存活执行进程的遗留任务置interrupted。

输入Bundle含sha256、source_id、original、pages、text、images、assets，DOCX可含source_warnings。输入路径由后端生成；不使用上传文件名拼接路径。

ExportSnapshot含id、items[{question完整快照,score,blank}]、params、warnings。params含title、kind(student/teacher/lesson)、draft、font、size、margin、line_spacing、show_score、answer_position以及教案文字。导出文件只由快照内容生成；后续题库变化不改旧快照或旧文件。
