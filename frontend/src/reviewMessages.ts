// Translate stored diagnostics at display time, including older imported records.
const labels: Record<string, string> = {
 'experimental scan figure; geometric rules do not prove label completeness': '扫描图片由系统自动识别，尚不能确认图中标注是否完整，请对照原图核对。',
 'near paragraph: inspect context': '图片靠近正文，请核对是否混入文字或遗漏相关内容。',
 page_coverage_incomplete: '本批页面内容未完整识别，请对照原件核对',
 page_coverage_unconfirmed: '本批页面覆盖情况尚未确认',
 cross_page_uncertain: '跨页题目内容尚未确认完整',
 cross_page_inconsistent: '跨页题目的页码或图片归属不一致，请核对',
 missing_image_asset: '缺少作答所需的图片',
 missing_asset: '缺少作答所需的图片或表格',
 missing_condition: '题干缺少必要条件',
 missing_option: '题目选项不完整',
 missing_subquestion: '题目小问不完整',
 wrong_assignment: '图片或表格与题目对应有误',
 image_text_conflict: '题目文字与图片存在矛盾',
 missing_critical_label: '图片缺少必要标注',
 missing_image_structure: '图片主体不完整',
 missing_table_information: '表格缺少关键信息',
 cross_page_missing_context: '缺少相邻页的题目内容',
 source_problem: '原材料内容存在疑点，请对照原件核对',
 uncertain_transcription: '关键文字或公式识别不确定，请对照原件核对',
 missing_question_text: '缺少题干文字',
 schema_partial_recovery: '仅恢复了部分识别内容，请核对题目是否完整',
 duplicate_option_label: '选项编号重复，请核对',
 duplicate_question_id: '题目标识重复，请核对',
 unsupported_page: '页面识别结果不确定，请对照原件核对',
 invalid_option_reference: '图片对应的选项无法确认',
 'geometry only; no OCR transcription': '仅识别了文字区域，尚未核对其中的文字',
 'uncertain geometry; not counted as figure success': '图片区域识别不确定，需人工核对',
 'residual ink; no semantic assumption': '存在未分类的图文内容，需人工核对',
 asset_catalog: '图片清单',
 'requires_image=true': '此题需要配图',
 '题目上下文尚未闭合': '跨页题目的前后文尚未补齐',
 '跨页内容尚未完整读取': '跨页题目的前后文尚未补齐',
 '跨页题的上下文尚未闭合，请补全前后页内容': '跨页题目的前后文尚未补齐，请补全相邻页内容',
 '合并结果未完整保留前页题文': '合并跨页题目时遗漏了前页文字，请对照原件补全',
 '纯D导入未执行质量检查，请人工审核': '本题尚未完成质量检查，请核对题目和配图',
 '已有调用记录但完成状态不确定；停止重发，请先核对API记录': '上次图片检查未返回完整结果，请对照原图核对',
};
export function reviewMessage(text: string): string {
 const flags: Record<string, [string, string]> = {
  contains_other_question_content: ['混入了其他题目的内容', '没有混入其他题目的内容'],
  belongs_to_question: ['图片与本题对应', '图片可能不属于本题'],
  critical_labels_present: ['必要标注齐全', '缺少必要标注'],
  readable: ['图片内容清晰可辨', '图片内容无法清楚辨认'],
  complete: ['图片内容完整', '图片内容不完整'],
  requires_image: ['此题需要配图', '此题不需要配图'],
 };
 let result = text;
 for (const [field, wording] of Object.entries(flags)) {
  result = result.replace(new RegExp('\\b'+field+'\\b[\\s"\']*(?:为|[:：=])[\\s"\']*(true|false)\\b', 'gi'), (_, value) => wording[value.toLowerCase() === 'true' ? 0 : 1]);
 }
 result = result.replace(/\bextra_content\b[\s"']*(?:为|[:：=])[\s"']*(minor|excessive|none)\b/gi,
  (_, value) => ({minor:'多余内容较少',excessive:'多余内容较多，需要清理',none:'没有多余内容'} as Record<string,string>)[value.toLowerCase()]);
 result = result.replace(/\bfigure_checks\b/g, '配图检查结果').replace(/第(\d+)个\s*block\b/g, '第$1个内容块');
 for (const [original, chinese] of Object.entries(labels)) result = result.split(original).join(chinese);
 return result
  .replace(/随\s*carry\s*带入本页/g, '从前页接续到本页')
  .replace(/控制器报告/g, '系统提示')
  .replace(/当前冻结资产清单/g, '本次识别的图片')
  .replace(/对应资产/g, '对应图片')
  .replace(/图象资产/g, '图象')
  .replace(/page-(\d+)\.png/g, '第$1页原图')
  .replace(/(?:asset-[a-f\d]{8,}|docx-native\d*-image-\d+)\.(?:png|jpe?g|webp|svg)/gi, '题图')
  .replace(/\b(?:fixed\s+)?assets?\b/gi, '题图')
  .replace(/(?:图片|题图|配图)\s*题图/g, '题图')
  .trim();
}

const plainKey = (text: string) => text.replace(/^第\s*\d+\s*题\s*/, '').replace(/[\s，,。；;：:]/g, '');
const generic = new Set([
 '原始题目存在疑点',
 '本题尚未完成质量检查，请核对题目和配图',
]);
const missingImage = new Set([
 '缺少作答所需的图片', '缺少作答所需图片', '缺少作答必要图表',
 '缺少作答所需的图片或表格', '缺少作答所需的题图或表格，请对照原页补全',
]);
const crossPage = new Set([
 '跨页题目的前后文尚未补齐', '跨页题目内容尚未确认完整',
 '跨页题目的前后文尚未补齐，请补全相邻页内容',
]);
const groupOf = (message: string) => {
 const key=message.replace(/[。！!]$/, '');
 return generic.has(key)?'generic':missingImage.has(key)?'image':crossPage.has(key)?'crossPage':null;
};

/** Compact repeated diagnostic summaries without changing stored review evidence.
 * A specific defect is always retained. Generic warnings remain when no detail
 * explains them, and formula strings are never split at semicolons or newlines.
 */
export function reviewMessages(messages: readonly string[] = []): string[] {
 const seen=new Set<string>();
 const translated=messages.filter(text=>typeof text==='string').map(reviewMessage).filter(text=>{
  const key=plainKey(text);if(!key||seen.has(key))return false;seen.add(key);return true;
 });
 const details=translated.filter(text=>!groupOf(text));
 const detailForImage=details.some(text=>text.split(/[。；]/).some(part=>
  !/(?:没有|未发现|不存在|未见).*(?:缺失|缺少)/.test(part)&&
  /(?:缺少|缺失|未提供|未在[^。；]*提供).*(?:图|表)|(?:图|表).*(?:缺少|缺失|未提供|未在[^。；]*提供)/.test(part)));
 const detailForCrossPage=details.some(text=>/跨页|前页|上一页|续题|前文/.test(text)&&/缺|未|漏|无法|不完整/.test(text));
 const shownGroups=new Set<string>();
 return translated.filter(text=>{
  const group=groupOf(text);if(!group)return true;
  if(group==='generic')return !details.length;
  if((group==='image'&&detailForImage)||(group==='crossPage'&&detailForCrossPage))return false;
  if(shownGroups.has(group))return false;shownGroups.add(group);return true;
 });
}
