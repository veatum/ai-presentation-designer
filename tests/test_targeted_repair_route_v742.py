import json, sys, types, tempfile
from pathlib import Path

m=types.ModuleType('openai')
class Base(Exception): pass
for name in ['APIStatusError','APIConnectionError','APITimeoutError','RateLimitError','InternalServerError']:
    setattr(m,name,type(name,(Base,),{}))
class OpenAI: pass
m.OpenAI=OpenAI
sys.modules['openai']=m
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app as web
from fastapi.testclient import TestClient

SOURCES=[{'id':'W1','kind':'web','verified':True,'title':'Verified source','url':'https://example.org/source','text':'The same content can be rendered on multiple templates without regenerating the meaning. '*20}]

def plan():
    slides=[]
    for n in range(1,5):
        slides.append({'number':n,'kind':'title' if n==1 else 'content','title':f'Slide {n}','subtitle':'','points':[] if n==1 else ['This is a sufficiently long explanatory block that carries a meaningful point for the audience and can be audited.','Another sufficiently long explanatory block connects the point to the implementation and source evidence.'],'left_points':[],'right_points':[],'left_title':'','right_title':'','metrics':[],'table':None,'chart':None,'quote':'','timeline':[],'notes':'','source_ids':['W1'] if n>1 else [],'claims':[{'text':'This is a sufficiently long explanatory block that carries a meaningful point for the audience and can be audited.','source_id':'W1','evidence_quote':'The same content can be rendered on multiple templates without regenerating the meaning. '*1}] if n>1 else []})
    return {'title':'Test','subtitle':'Test','audience':'Test','purpose':'Test','slides':slides}

def test_repair_endpoint_accepts_only_selected_findings(monkeypatch):
    web.RUNS=Path(tempfile.mkdtemp(prefix='targeted_repair_'))
    web.generate_plan=lambda *a,**k: plan()
    web.research=lambda *a,**k: {'sources':SOURCES,'domains':['example.org'],'warnings':[]}
    web.export_pdf=lambda *a,**k: (_ for _ in ()).throw(ValueError('skip'))
    web.export_pdfs_batch=lambda *a,**k: {}
    received=[]
    def fake_repair(p,a,sources=None,session=None): received.append(a); return p
    monkeypatch.setattr(web,'repair_plan',fake_repair)
    client=TestClient(web.app)
    r=client.post('/api/generate',data={'brief':'test','slides':'4','include_vk_templates':'false','include_images':'false'})
    assert r.status_code==200, r.text
    run_id=r.json()['run_id']
    chosen={'slide':2,'severity':'major','problem':'Проверить overlap','fix':'Разнести блоки'}
    rr=client.post(f'/api/repair/{run_id}',data={'selected_issues':json.dumps([chosen],ensure_ascii=False)})
    assert rr.status_code==200, rr.text
    assert received[0]['audits']==[chosen]
