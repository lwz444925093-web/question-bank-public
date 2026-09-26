from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal, Optional
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Span(Strict):
    kind: Literal['text','math','image']
    text: str
    width: Optional[float]=Field(default=None,gt=0,le=2000)
    height: Optional[float]=Field(default=None,gt=0,le=2000)
class Shape(Strict):
    kind: Literal['point','line','circle','label']
    x: float
    y: float
    x2: float
    y2: float
    radius: float
    label: str
class Block(Strict):
    kind: Literal['paragraph','equation','table','geometry','image']
    spans: list[Span]
    latex: str
    rows: list[list[list[Span]]]
    shapes: list[Shape]
    asset: str
    @model_validator(mode='before')
    @classmethod
    def normalize_table_cells(cls,data):
        if isinstance(data,dict) and data.get('kind')=='table':
            data=dict(data)
            data['rows']=[[[cell] if isinstance(cell,dict) and cell.get('kind') in ['text','math'] else cell for cell in row] for row in data.get('rows',[])]
        return data
    @model_validator(mode='after')
    def valid(self):
        if self.kind=='table' and (not self.rows or not self.rows[0] or len({len(r) for r in self.rows})!=1): raise ValueError('表格必须为非空矩形')
        if self.kind=='geometry' and not self.shapes: raise ValueError('几何图对象为空')
        return self
class Part(Strict):
    label: str
    blocks: list[Block]
class SourceRegion(Strict):
    page:int=Field(gt=0,strict=True)
    box:list[float]=Field(min_length=4,max_length=4)
    part:int=Field(default=1,gt=0)
    @model_validator(mode='after')
    def valid(self):
        from .vision_inputs import checked_box
        checked_box(self.box)
        return self
class Extracted(Strict):
    original_number: str
    subject: str
    grade: str
    question_type: str
    knowledge: list[str]
    difficulty: str
    stem: list[Block]
    options: list[Part]
    subquestions: list[Part]
    original_answer: list[Block]
    original_explanation: list[Block]
    ai_answer: list[Block]
    ai_explanation: list[Block]
    pitfalls: list[str]
    issues: list[str]
    pages: list[int]
    review_notes: list[str]=Field(default_factory=list)
    review_tags: list[str]=Field(default_factory=list)
    source_regions:list[SourceRegion]=Field(default_factory=list)
class PageExtraction(Strict):
    page: int=Field(gt=0,strict=True)
    status: Literal["complete","no_questions","incomplete"]
    question_count: int=Field(ge=0,strict=True)
    reason: str
class ParseResult(Strict):
    schema_version: Literal['1.0']
    questions: list[Extracted]=Field(min_length=0,max_length=30)
    page_extractions: list[PageExtraction]=Field(default_factory=list)
def paragraph(text):
    return dict(kind='paragraph',spans=[dict(kind='text',text=text)],latex='',rows=[],shapes=[],asset='')
