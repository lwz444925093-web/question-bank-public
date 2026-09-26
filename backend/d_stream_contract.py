"""One current page plus explicit unfinished-question context, no previous full page."""
from typing import Optional
from pydantic import Field,StrictInt
from .d_delivery_contract import Question as DeliveryQuestion,Assignment,Page,Strict,PROMPT as BASE
from .d_contract import Question as BaseQuestion

class Transcription(BaseQuestion):
 source_pages:list[StrictInt]=Field(min_length=1,max_length=32)

class Question(DeliveryQuestion):
 source_pages:list[StrictInt]=Field(min_length=1,max_length=32)
 continuation_of:Optional[str]
 context_closed:bool

class Output(Strict):
 questions:list[Question]
 asset_assignments:list[Assignment]
 page_extractions:list[Page]
 issues:list[str]

PROMPT=BASE.replace('每题source_pages只能来自输入的一页或相邻两页；资产所有来源页必须包含于题目页。完整跨两页题仅输出一次，continues_from_previous且source_pages两页；仍需未提供页则保留片段并标starts_on_page_continues_next/continues_from_previous（单页）或cross_page_uncertain及具体缺失。不按相同题号盲目合并。每页如实报告complete/no_questions/incomplete。','''每次只有一张当前完整原页，pages/source_pages只标识本次实际视觉读取页。carry_forward是前页尚未闭合题目已经识别的文字、选项、小问、固定asset和source状态，不是重新读取的原页。只延续与当前页确有连续关系的carry，不按题号猜测关联。
匹配carry时continuation_of必须原样返回对应carry_id；返回该题合并后的完整question_text/options/subquestions与涉及的全部source_pages，保留carry已识别的全部条件。未匹配题continuation_of=null。合并完成时cross_page_status=continues_from_previous且context_closed=true；依然缺后文则context_closed=false。单页完整题complete_on_page且context_closed=true；页尾半题starts_on_page_continues_next且context_closed=false；孤立续题或不能判断关联cross_page_uncertain且context_closed=false。不要因有了可猜出的答案就把上下文标闭合。
每个输入carry都必须在questions返回一次，即使未找到续文也保留已提取信息并标context_closed=false、具体缺什么。只有完整题才能标solution.ready；半题solution.needs_review，不猜答案。
page_extractions只报告当前实际页：所有可见文字和图表均已转录（包括页尾半题），即可complete；只因题目延续到下一页不能把页面标incomplete。确实漏读/不可辨认才incomplete。题目是否闭合由context_closed独立表示。''')+'''
associated_text仅保存正文、选项、小问中未出现且确有必要与图片绑定的短标签、单位或图注。不要重复question_text、整段条件或已有表格文本。
'''

# These contracts apply only to the current streaming path; legacy D stays intact.
from .d_boundary import PROMPT as BOUNDARY_PROMPT
PROMPT+=BOUNDARY_PROMPT
from typing import Literal
from .d_delivery_contract import Delivery, Solution

class EstimatedMetadata(Strict):
 subject:str
 question_type:str
 knowledge_tags:list[str]
 estimated_difficulty:Optional[Literal['容易','中等','较难','uncertain']]
 common_mistakes:list[str]

class ImportMetadata(Strict):
 subject:str
 question_type:str
 knowledge_tags:list[str]
 estimated_difficulty:Optional[Literal['容易','中等','较难','uncertain']]

class EvidenceDelivery(Delivery):
 critical_source_ambiguity:bool=False

class EvidenceSolution(Solution):
 status:Literal['ready','needs_review','failed','unavailable_due_to_source_issue']

class DisabledSolution(Strict):
 status:Literal['disabled']

class SolvedQuestion(Question):
 metadata:EstimatedMetadata
 solution:EvidenceSolution
 delivery_check:EvidenceDelivery

class ImportQuestion(Question):
 metadata:ImportMetadata
 solution:DisabledSolution
 delivery_check:EvidenceDelivery

class SolvedOutput(Output):
 questions:list[SolvedQuestion]

class ImportOutput(Output):
 questions:list[ImportQuestion]

STOP_RULE = r"""
视觉歧义停止规则（优先于解题要求）：当固定asset与完整原页的关键数字、标签、单位、图例、刻度或几何点名冲突或缺失，立即在delivery_check.issues记录具体asset_id、差异与证据。不得猜测缺失像素，不得反复尝试数学解释来消解视觉歧义，不用多想来补偿不确定来源。
完整原页若能明确、无歧义地提供信息，可以按原页文字转录；仍必须保留固定asset的问题，不能因为转录了文字就抹掉问题。若歧义影响正常作答，solvable_from_current_delivery=false并报告实质issue，交由人工审核。
critical_source_ambiguity表示按上述明确原页转录后仍存在影响正常作答的关键证据歧义。若为true，立即停止解题：开启solution时status=unavailable_due_to_source_issue，answer和explanation为空，issues说明来源问题；关闭solution时保持disabled。不通过求解反推正确像素。
estimated_difficulty仅为题面难度估计：根据题面结构、条件数量、知识点组合、图表复杂度、小问结构判断，不是完整求解后的难度。可填容易/中等/较难/uncertain或null。
"""

def configuration(generate_solution=True):
 if type(generate_solution) is not bool:raise ValueError('generate_solution必须为布尔值')
 prompt=PROMPT.replace('metadata在理解并尝试解题后生成','metadata根据题面可见信息生成').replace('difficulty用容易/中等/较难','estimated_difficulty用容易/中等/较难或uncertain/null')
 if not generate_solution:
  prompt=prompt.replace('一次输出转录、归属、metadata、答案解析和交付事实检查','一次输出转录、归属、题面metadata和交付事实检查')
  prompt=prompt.replace('再仅依照它们解题和检查','再仅依照它们检查内容是否足以理解和作答，不实际解题')
  start=prompt.index('solution.answer是学生可使用的规范答案')
  end=prompt.index('\ndelivery_check报告',start)
  prompt=prompt[:start]+"""generate_solution=false。solution仅输出{"status":"disabled"}，不输出answer、explanation、common_mistakes，不执行solution_check，不生成解题步骤，不为答案另发请求。
不要为了生成knowledge_tags、question_type或estimated_difficulty完整求解题目。可选metadata若必须依赖完整求解才能可靠确定，宁可保守输出uncertain/null（knowledge_tags可为空数组），不要进行长链求解。标签仅为题面有依据的知识点，不用流程状态充当知识点。内容检查只检查转录、条件及图表是否完整，不计算答案来验证可解性。"""+prompt[end:]
  prompt=prompt.replace('只有完整题才能标solution.ready；半题solution.needs_review，不猜答案。','所有题包括半题solution.status均为disabled，不猜答案。')
  prompt=prompt.replace('无法生成solution也保留转录与delivery_check','保留转录与delivery_check，solution只保留disabled状态')
 else:prompt+='\ngenerate_solution=true。保持规范答案、解析及易错点生成。\n'
 return prompt+STOP_RULE, ImportOutput if not generate_solution else SolvedOutput
