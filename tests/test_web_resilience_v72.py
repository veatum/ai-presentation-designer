import sys, types, time
from pathlib import Path

try:
    import openai  # noqa: F401
except Exception:
    m=types.ModuleType('openai')
    class Base(Exception): pass
    for name in ['APIStatusError','APIConnectionError','APITimeoutError','RateLimitError','InternalServerError']:
        setattr(m,name,type(name,(Base,),{}))
    class OpenAI: pass
    m.OpenAI=OpenAI;sys.modules['openai']=m

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.web_research import _parse_markdown_search_results, fetch, public_url
from core.llm import generate_plan, Session
import core.llm as llm
from types import SimpleNamespace


def test_jina_markdown_search_parser_drops_search_engines():
    text='[Official report](https://example.org/report)\n[Study](https://uni.example.edu/study)\n[Google](https://www.google.com/search?q=x)'
    rows=_parse_markdown_search_results(text)
    assert [x['url'] for x in rows]==['https://example.org/report','https://uni.example.edu/study']


def test_url_validation_does_not_require_working_local_dns(monkeypatch):
    def fail(*args,**kwargs): raise OSError('DNS unavailable')
    monkeypatch.setattr('core.web_research.socket.getaddrinfo',fail)
    assert public_url('https://example.org/article')=='https://example.org/article'


def test_fetch_uses_jina_when_direct_request_fails(monkeypatch):
    class BadSession:
        trust_env=True
        def get(self,*args,**kwargs): raise RuntimeError('direct network down')
    monkeypatch.setattr('core.web_research.requests.Session',lambda: BadSession())
    monkeypatch.setattr('core.web_research._request_jina',lambda url,deadline:'# Article\n\n'+'Verified source content. '*80)
    final,data,ctype=fetch('https://example.org/article',time.monotonic()+20)
    assert final=='https://example.org/article'
    assert b'Verified source content' in data
    assert 'jina-reader' in ctype


def test_generate_plan_falls_back_without_web_sources(monkeypatch):
    class FakeClient:
        def __init__(self,**kwargs): self.chat=SimpleNamespace(completions=self)
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def create(self,**kwargs):
            import json
            user=json.loads(kwargs['messages'][1]['content']); system=kwargs['messages'][0]['content']
            if 'core_thesis' in system and 'visual_logic' in system:
                n=int(user.get('requested_slides',10))
                return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps({'story':'story','core_thesis':'thesis','slides':[{'number':i,'role':'content','key_question':'q','key_message':f'Message {i}','evidence_needed':[],'source_ids':[],'visual_logic':'v'} for i in range(1,n+1)]})))],usage=None)
            nums=user.get('required_slide_numbers',[1])
            slides=[]
            for n in nums:
                if n==1: slides.append({'number':1,'kind':'title','title':'Fallback deck','subtitle':'','points':[],'source_ids':[]})
                else: slides.append({'number':n,'kind':'content','title':f'Message {n}','points':['This is a sufficiently detailed explanatory block created for the offline fallback path without making unsupported precise numerical claims.','This second block explains the mechanism and consequence so the presentation remains usable when the external web network is temporarily unavailable.'],'source_ids':[]})
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content=json.dumps({'slides':slides})))],usage=None)
    old_openai,llm.OpenAI=llm.OpenAI,FakeClient
    old_settings=llm.settings
    llm.settings=SimpleNamespace(api_key='x',base_url='https://example.org/v1',model='Qwen/Qwen3-32B',structured_output='json_object',api_timeout=10,api_retries=0,session_seconds=290,max_llm_calls=20,max_slides=15,disable_thinking=True)
    try:
        plan=generate_plan('Сделай презентацию о цифровой трансформации.',{},'',10,{'sources':[]},session=Session())
        assert len(plan['slides'])==10
    finally:
        llm.OpenAI=old_openai; llm.settings=old_settings
