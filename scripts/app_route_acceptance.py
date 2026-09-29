import json, sys, types, tempfile
from pathlib import Path

# Offline OpenAI stub: this test exercises the FastAPI route and render/export layers,
# not the external provider.
m = types.ModuleType('openai')
class Base(Exception): pass
for name in ['APIStatusError','APIConnectionError','APITimeoutError','RateLimitError','InternalServerError']:
    setattr(m,name,type(name,(Base,),{}))
class OpenAI: pass
m.OpenAI=OpenAI
sys.modules['openai']=m

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as web
from fastapi.testclient import TestClient
from core.template_profiles import BUILTIN_TEMPLATES
from core.renderer import VARIANTS
from pptx import Presentation

SOURCES=[{
    'id':'W1','kind':'web','verified':True,'title':'Verified source','url':'https://example.org/source',
    'text':' '.join([
        'The service uses structured output to produce valid data for downstream rendering.',
        'The same content can be rendered on multiple templates without regenerating the meaning.',
        'Three visually distinct layout variants can be generated for comparison.',
    ]*10)
}]

def block(i):
    return f'Этот смысловой блок {i} объясняет механизм и практическое следствие для пользователя, связывая утверждение с проверяемым источником и конкретным этапом пайплайна.'

def sample_plan():
    slides=[]
    for n in range(1,11):
        if n==1:
            slides.append({'number':1,'kind':'title','title':'Проверенная генерация презентаций','subtitle':'Источники → содержание → шаблон','points':[],'left_points':[],'right_points':[],'source_ids':['W1'],'claims':[]})
        elif n%3==0:
            slides.append({'number':n,'kind':'two_column','title':f'Слайд {n}','left_title':'Механизм','left_points':[block(n),block(n+1)],'right_title':'Следствие','right_points':[block(n+2),block(n+3)],'source_ids':['W1'],'claims':[{'text':block(n),'source_id':'W1','evidence_quote':'The service uses structured output to produce valid data for downstream rendering.'}]})
        elif n%4==0:
            slides.append({'number':n,'kind':'process','title':f'Процесс {n}','timeline':[{'label':'Источники','detail':block(n)},{'label':'Проверка','detail':block(n+1)},{'label':'Рендер','detail':block(n+2)}],'source_ids':['W1'],'claims':[{'text':block(n),'source_id':'W1','evidence_quote':'The same content can be rendered on multiple templates without regenerating the meaning.'}]})
        else:
            slides.append({'number':n,'kind':'content','title':f'Слайд {n}','points':[block(n),block(n+1)],'source_ids':['W1'],'claims':[{'text':block(n),'source_id':'W1','evidence_quote':'The service uses structured output to produce valid data for downstream rendering.'}]})
    return {'title':'Тестовая колода','subtitle':'Проверка маршрута','audience':'Эксперт','purpose':'Тест','slides':slides}

web.RUNS=Path(tempfile.mkdtemp(prefix='route_test_'))
web.generate_plan=lambda *args,**kwargs: sample_plan()
web.research=lambda *args,**kwargs: {'sources':SOURCES,'domains':['example.org'],'warnings':[]}
web.export_pdf=lambda *args,**kwargs: (_ for _ in ()).throw(ValueError('skip pdf in route test'))
web.export_pdfs_batch=lambda *args,**kwargs: {}

client=TestClient(web.app)
r=client.post('/api/generate',data={'brief':'test','slides':'10','include_vk_templates':'true'})
assert r.status_code==200, r.text
payload=r.json()
results=payload['results']
assert len(results)==len(BUILTIN_TEMPLATES)*len(VARIANTS)==9, len(results)
assert set(x['template_id'] for x in results)==set(BUILTIN_TEMPLATES)
assert set(x['variant'] for x in results)==set(VARIANTS)
for result in results:
    assert result['pptx'], result
    path=web.RUNS/payload['run_id']/result['pptx']
    prs=Presentation(str(path))
    assert len(prs.slides)==10
print('APP ROUTE PASS',len(results))

