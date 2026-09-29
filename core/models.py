"""Versioned contract shared by generation, validation and all renderers."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Table(Model):
    columns: list[str] = Field(min_length=1, max_length=8)
    rows: list[list[str]] = Field(min_length=1, max_length=12)

    @model_validator(mode='after')
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('Table rows must match columns')
        return self

class Chart(Model):
    type: Literal['bar', 'column', 'line', 'pie']
    labels: list[str] = Field(min_length=2, max_length=20)
    values: list[float] = Field(min_length=2, max_length=20)
    unit: str = Field(min_length=1, max_length=60)

    @model_validator(mode='after')
    def matching(self):
        if len(self.labels) != len(self.values):
            raise ValueError('Chart labels and values must match')
        if self.type == 'pie' and (min(self.values) < 0 or sum(self.values) <= 0):
            raise ValueError('Pie chart needs nonnegative values and positive total')
        return self

class Metric(Model):
    label: str
    value: str
    note: str

class Step(Model):
    label: str
    detail: str

class Claim(Model):
    text: str = Field(min_length=1)
    source_id: str
    evidence_quote: str = Field(min_length=1, max_length=4000)

class Slide(Model):
    number: int = Field(ge=1)
    kind: Literal['title','section','content','two_column','metrics','table','chart','quote','timeline','process','summary','sources']
    title: str = Field(min_length=1, max_length=180)
    subtitle: str = Field(default='', max_length=320)
    points: list[str] = Field(default_factory=list, max_length=20)
    left_title: str = ''
    left_points: list[str] = Field(default_factory=list, max_length=12)
    right_title: str = ''
    right_points: list[str] = Field(default_factory=list, max_length=12)
    metrics: list[Metric] = Field(default_factory=list, max_length=10)
    table: Table | None = None
    chart: Chart | None = None
    quote: str = ''
    timeline: list[Step] = Field(default_factory=list, max_length=10)
    notes: str = Field(default='', max_length=4000)
    source_ids: list[str] = Field(default_factory=list, max_length=24)
    claims: list[Claim] = Field(default_factory=list, max_length=64)

    @model_validator(mode='after')
    def payload_matches_kind(self):
        supported = {'table':{'table'}, 'chart':{'chart'}, 'metrics':{'metrics'}, 'timeline':{'timeline','process'},
                     'left_title':{'two_column'},'right_title':{'two_column'},'left_points':{'two_column'},'right_points':{'two_column'},'quote':{'quote'}}
        for field,kinds in supported.items():
            if getattr(self,field) and self.kind not in kinds:
                raise ValueError(f'{field} is not rendered by kind={self.kind}; select the correct kind')
        if self.chart and self.table:
            raise ValueError('Separate chart and table slides')
        if self.kind == 'chart' and not self.chart:
            raise ValueError('Chart slide needs chart data')
        if self.kind == 'table' and not self.table:
            raise ValueError('Table slide needs table data')
        if self.kind in ('timeline','process') and not self.timeline:
            raise ValueError('Process/timeline needs steps')
        if self.kind == 'metrics' and not self.metrics:
            raise ValueError('Metrics slide needs metrics')
        if self.kind == 'two_column' and (not self.left_points or not self.right_points):
            raise ValueError('Comparison needs both columns')
        return self

class Deck(Model):
    title: str = Field(min_length=1, max_length=180)
    subtitle: str = ''
    audience: str = ''
    purpose: str = ''
    slides: list[Slide] = Field(min_length=1, max_length=30)

class SlideBatch(Model):
    slides: list[Slide] = Field(min_length=1, max_length=15)

class OutlineSlide(Model):
    number: int
    role: str
    key_question: str
    key_message: str
    evidence_needed: list[str]
    source_ids: list[str]
    visual_logic: str

class Architecture(Model):
    story: str
    core_thesis: str
    slides: list[OutlineSlide]

class Finding(Model):
    slide: int
    severity: Literal['critical','major','minor']
    problem: str
    fix: str

class Critique(Model):
    overall: Literal['pass','repair']
    issues: list[Finding]
    global_fixes: list[str]

class SearchJob(Model):
    query: str
    domain: str
    reason: str

class SearchPlan(Model):
    jobs: list[SearchJob] = Field(max_length=6)

def strict_schema(model):
    def walk(node):
        if isinstance(node, list): return [walk(v) for v in node]
        if not isinstance(node, dict): return node
        node = {k:walk(v) for k,v in node.items() if k != 'default'}
        if node.get('type') == 'object':
            node['additionalProperties'] = False
            node['required'] = list(node.get('properties',{}))
        return node
    return walk(model.model_json_schema())

def visible_text(slide):
    """Single content inventory: never count speaker notes as slide content."""
    parts = [slide.get('subtitle','')]
    for key in ('points','left_points','right_points'):
        parts.extend(slide.get(key,[]))
    parts.extend([slide.get('left_title',''),slide.get('right_title',''),slide.get('quote','')])
    for m in slide.get('metrics',[]): parts.extend([m['label'],m['value'],m['note']])
    for step in slide.get('timeline',[]): parts.extend([step['label'],step['detail']])
    if slide.get('table'):
        parts.extend(slide['table']['columns'])
        for row in slide['table']['rows']: parts.extend(row)
    if slide.get('chart'):
        parts.extend(slide['chart']['labels'])
        parts.extend(format(v,'.12g') for v in slide['chart']['values'])
        parts.append(slide['chart']['unit'])
    return [str(x) for x in parts if str(x).strip()]
