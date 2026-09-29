"""Explicit paid smoke check: run manually, never collected by pytest."""
import json,time
from pathlib import Path
from core.default_template import build_default_template
from core.template_parser import parse_template
from core.llm import generate_plan,Session
from core.web_research import research
from core.renderer import render_variant
from core.audit import audit_deck
from core.exporter import export_pdf,export_html

out=Path('outputs/live-check'); out.mkdir(parents=True,exist_ok=True)
ss=Session(); start=time.monotonic()
try:
    web=research('Cloud.ru Foundation Models Qwen Qwen3-32B API',max_jobs=4,budget_seconds=60,session=ss)
    sources=web.get('sources',[])
    if not any(s.get('kind')=='web' and s.get('verified') for s in sources):
        raise RuntimeError('Live research did not return a verified web source')
    tpl=build_default_template(out/'base.pptx')
    brief=('Объясни разработчикам, как работает OpenAI-совместимый API Cloud.ru Foundation Models, '
           'какие возможности доступны у Qwen/Qwen3-32B, какие ограничения важны при интеграции, '
           'и какие проверки нужно выполнить перед использованием. Дай источники.')
    plan=generate_plan(brief,parse_template(tpl),'',5,{'sources':sources},session=ss)
    for name,value in [('plan',plan),('sources',sources)]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    path=render_variant(tpl,plan,parse_template(tpl),out/'live.pptx','balanced',sources=sources)
    report=audit_deck(path,plan); print('AUDIT',report,flush=True)
    assert not report['issues']
    pdf=export_pdf(path,out); export_html(path,out/'live.html',pdf)
    print('SUCCESS',len(plan['slides']),'seconds',round(time.monotonic()-start,1),flush=True)
except Exception as e:
    print('FAILED',type(e).__name__,str(e),flush=True)
finally:
    (out/('trace_'+str(int(time.time()))+'.json')).write_text(json.dumps({'calls':ss.calls,'artifacts':ss.artifacts},ensure_ascii=False,indent=2),encoding='utf-8')
    print('CALLS',len(ss.calls),flush=True)
