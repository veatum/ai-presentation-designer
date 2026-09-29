"""Offline contract smoke test for the final package.
It simulates several common Qwen formatting mistakes, then runs the real
normalization, QA, PPTX renderer and all bundled VK templates.
"""
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import openai  # noqa: F401
except ImportError:
    m=types.ModuleType("openai")
    class Base(Exception): pass
    for _n in ["APIStatusError","APIConnectionError","APITimeoutError","RateLimitError","InternalServerError"]:
        setattr(m,_n,type(_n,(Base,),{}))
    class OpenAI: pass
    m.OpenAI=OpenAI
    sys.modules["openai"]=m

import core.llm as llm
from core.default_template import build_default_template
from core.template_parser import parse_template
from core.quality import quality_issues, source_issues, harden_plan, bibliography
from core.models import Slide
from core.renderer import render_variant
from core.audit import audit_deck
from core.exporter import export_pdf, export_html
from core.template_profiles import BUILTIN_TEMPLATES, builtin_template_path

OUT=Path('examples/smoke-tested'); OUT.mkdir(parents=True,exist_ok=True)

SOURCE_TEXT=(
    'В разделе представлена информация об AI-моделях, доступных в Foundation Models. '
    'Foundation Models поддерживает несколько специализированных типов моделей искусственного интеллекта, каждая из которых оптимизирована для решения определенного класса задач. '
    'Модели могут поддерживать следующие функции, которые расширяют их возможности. Function Calling — вызов внешних функций и API через структурированный запрос. '
    'Structure Output — гарантированный вывод данных в заданном формате JSON, XML и др. Reasoning — расширенные логические возможности и многошаговые рассуждения. '
    'Qwen/Qwen3-32B | LLM | Внешняя | Function Calling, Structure Output, Reasoning | 40 960 | Alibaba Cloud. '
    'Совместимая со схемой OpenAI OpenAPI-спецификация для Foundation Models, ограниченная двумя методами: GET /v1/models и POST /v1/chat/completions. '
    'Генерация ответов в стиле чата выполняется методом POST /v1/chat/completions. '
)
SOURCES=[
    {'id':'W_SMOKE_1','kind':'web','verified':True,'title':'Обзор доступных AI-моделей — Cloud.ru',
     'url':'https://cloud.ru/docs/foundation-models/ug/topics/overview__available__models',
     'text':SOURCE_TEXT,'site_name':'Cloud.ru'},
    {'id':'W_SMOKE_2','kind':'web','verified':True,'title':'Cloud.ru Foundation Models API — Cloud.ru',
     'url':'https://cloud.ru/docs/foundation-models/ug/topics/api-ref__specs',
     'text':'Совместимая со схемой OpenAI OpenAPI-спецификация для Foundation Models, ограниченная двумя методами: GET /v1/models и POST /v1/chat/completions. Генерация ответов в стиле чата выполняется методом POST /v1/chat/completions. Запрос содержит обязательные поля messages и model, а также поддерживает параметры max_completion_tokens, response_format, temperature и top_p.',
     'site_name':'Cloud.ru'}
]

B1=(
    'Foundation Models предлагает несколько классов моделей, поэтому выбор конкретного варианта должен соответствовать типу задачи и требуемым возможностям интеграции. '
)
B2=(
    'Для структурированной генерации важен Structure Output: сервис предназначен для выдачи результата в заданном формате, что уменьшает количество ручной обработки ответа. '
)
B3=(
    'Qwen/Qwen3-32B сочетает генерацию текста с Function Calling, Structure Output и Reasoning, поэтому приложение может строить сложные многоэтапные сценарии вокруг одной модели. '
)
B4=(
    'OpenAI-совместимый интерфейс задаёт единый способ обращения к Foundation Models через стандартные chat completions, что упрощает перенос существующей клиентской интеграции. '
)
B5=(
    'Вызов chat completions использует сообщения и идентификатор модели как обязательную основу запроса, а остальные параметры управляют форматом и поведением генерации. '
)
B6=(
    'Structure Output полезен в проекте презентаций, потому что содержание можно сначала проверить программно, а только затем передать подтверждённые данные в слой визуального рендеринга. '
)
B7=(
    'Разделение содержания и оформления снижает влияние шаблона на смысл: модель формирует единую структуру, после чего разные PPTX-макеты получают одинаковое проверенное содержание. '
)
B8=(
    'Автоматическая проверка JSON и Pydantic должна идти до рендера, чтобы ошибки формата не превращались в повреждённые презентации и не тратили время на экспорт. '
)
B9=(
    'Финальная проверка связывает видимые утверждения с источниками и не позволяет считать наличие URL достаточным доказательством без реально загруженного текста страницы. '
)

BLOCKS=[B1,B2,B3,B4,B5,B6,B7,B8,B9]


def slide(n,kind,title,blocks):
    base={'number':n,'kind':kind,'title':title,'subtitle':'','points':[],'left_title':'','left_points':[],'right_title':'','right_points':[],
          'metrics':[],'table':None,'chart':None,'quote':'','timeline':[],'notes':'','source_ids':['W_SMOKE_1'],'claims':[]}
    if kind in ('content','summary'):
        base['points']=blocks
    elif kind=='two_column':
        base['left_title']='Модель'; base['right_title']='Интеграция'; base['left_points']=[blocks[0],blocks[1]]; base['right_points']=[blocks[2],blocks[3]]
    elif kind=='process':
        base['timeline']=[{'label':f'Шаг {i+1}','detail':x} for i,x in enumerate(blocks)]
    else:
        base['points']=blocks
    return base


calls=[]
class FakeClient:
    def __init__(self,**kwargs): self.kwargs=kwargs; self.chat=SimpleNamespace(completions=self)
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def create(self,**kwargs):
        calls.append(kwargs)
        user=json.loads(kwargs['messages'][1]['content'])
        stage=len(calls)
        system=kwargs['messages'][0]['content']
        if 'core_thesis' in system and 'visual_logic' in system:
            payload={'story':'От модели к проверенному PPTX через API, QA и render-only шаблоны.','core_thesis':'Надёжность достигается разделением содержания, проверки и оформления.',
                'slides':[{'number':i+1,'role':'content','key_question':f'Вопрос {i+1}','key_message':BLOCKS[min(i,8)],'evidence_needed':['официальная документация'],'source_ids':['W_SMOKE_1'],'visual_logic':'Объясняющий блок'} for i in range(9)]}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='```json\n'+json.dumps(payload,ensure_ascii=False)+'\n```'))],usage=None)
        if 'overall' in system and 'global_fixes' in system:
            payload={'overall':'pass','issues':[],'global_fixes':[]}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps(payload,ensure_ascii=False)))],usage=None)
        nums=user.get('required_slide_numbers',[1])
        out=[]
        # Deliberately make the first write call malformed in a way the local coercer can repair.
        for idx,n in enumerate(nums):
            if n==1:
                out.append({'slideNo':'1','type':'title','heading':'Как устроена надёжная генерация презентации','subheading':'От API и источников к редактируемому PPTX','bullets':[],'sourceIds':[],'extra':'ignored'})
            elif n==3:
                out.append({'number':'3','type':'comparison','heading':'Что делает модель и что делает приложение','bullets':[B1,B2,B4,B5], 'leftTitle':'Модель','rightTitle':'Приложение','sourceIds':['W_SMOKE_1']})
            elif n==4 or n==7:
                out.append({'number':n,'kind':'steps','title':f'Пайплайн проверки: этап {n}','steps':[{'label':'Источники','detail':B1},{'label':'Структура','detail':B2},{'label':'Рендер','detail':B6}]})
            elif n==9:
                out.append({'number':n,'kind':'conclusion','title':'Что проверяется перед выпуском','points':[B8,B9]})
            else:
                out.append({'number':n,'kind':'content','title':f'Смысловой этап {n}','points':[BLOCKS[(n-2)%len(BLOCKS)],BLOCKS[(n-1)%len(BLOCKS)]] ,'source_ids':['W_SMOKE_1']})
        # On the second write batch, return two top-level objects once; _complete must retry.
        if stage==3:
            raw=json.dumps({'slides':out},ensure_ascii=False)+' '+json.dumps({'slides':out},ensure_ascii=False)
        else:
            raw=json.dumps({'slides':out},ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=raw))],usage=None)

old=llm.OpenAI
llm.OpenAI=FakeClient
old_settings=llm.settings
llm.settings=SimpleNamespace(api_key='test',base_url='https://example.invalid/v1',model='Qwen/Qwen3-32B',structured_output='json_object',api_timeout=30,api_retries=1,session_seconds=600,max_llm_calls=36,max_slides=15)

try:
    from core.llm import generate_plan,Session
    session=Session(); brief='Покажи, как работает Qwen/Qwen3-32B в OpenAI-совместимом API, почему Structure Output важен для генерации презентаций, и добавь источники.'
    plan=generate_plan(brief,{},'',10,{'sources':SOURCES},session=session)
    issues=quality_issues(plan,10)+source_issues(plan,SOURCES)
    assert not issues, issues
    assert len(plan['slides'])==10
    assert len({s['kind'] for s in plan['slides'] if s['kind'] not in ('title','sources','section')})>=3
    (OUT/'trial_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'trial_sources.json').write_text(json.dumps(SOURCES,ensure_ascii=False,indent=2),encoding='utf-8')

    base=build_default_template(OUT/'base_template.pptx')
    for tid in ['base','vk_tech','vk_workspace','vk_education']:
        tpl=base if tid=='base' else builtin_template_path(tid)
        output=OUT/f'trial_{tid}.pptx'
        render_variant(tpl,plan,parse_template(tpl),output,'balanced',sources=SOURCES)
        report=audit_deck(output,plan)
        assert 'score' in report and 'issues' in report and 'stats' in report, report
        assert report['stats']['slides'] == len(plan['slides']), report
        pdf=export_pdf(output,OUT)
        export_html(output,OUT/f'trial_{tid}.html',pdf)
        print(tid,'OK')
    (OUT/'SMOKE_RESULT.txt').write_text(f'PASS\\nslides={len(plan["slides"])}\\nllm_calls={len(calls)}\\n',encoding='utf-8')
finally:
    llm.OpenAI=old
    llm.settings=old_settings

print('SMOKE PASS; calls=',len(calls))
