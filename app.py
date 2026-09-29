from __future__ import annotations
import json,shutil,uuid,time,re,threading,traceback,os
from pathlib import Path
from typing import List
from zipfile import ZipFile,BadZipFile
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from core.config import settings
from core.default_template import build_default_template
from core.extract import extract_source_records
from core.llm import generate_plan,repair_plan,revise_plan,Session
from core.template_parser import parse_template
from core.renderer import render_variant,VARIANTS
from core.template_profiles import BUILTIN_TEMPLATES,builtin_catalog,builtin_template_path
from core.web_research import research
from core.image_research import collect_images
from core.audit import audit_deck
from core.exporter import export_html,export_pdf,export_preview_png,export_pdfs_batch

ROOT=Path(__file__).resolve().parent
RUNS=ROOT/'outputs'/'runs'
RUNS.mkdir(parents=True,exist_ok=True)
STATIC_DIR=ROOT/'static'
INDEX_FILE=STATIC_DIR/'index.html'
APP_BUILD_ID='7.4.2-final'
if not STATIC_DIR.is_dir() or not INDEX_FILE.is_file():
    raise RuntimeError(f'Не найден интерфейс проекта: {INDEX_FILE}')
app=FastAPI(title='Digital Presentation Designer',version='7.4.2')
app.mount('/static',StaticFiles(directory=str(STATIC_DIR)),name='static')
LOCK=threading.Lock()

ERROR_LOG=ROOT/'outputs'/'server_error.log'

def _log_unhandled(exc):
    ERROR_LOG.parent.mkdir(parents=True,exist_ok=True)
    with ERROR_LOG.open('a',encoding='utf-8') as f:
        f.write('\n'+'='*88+'\n')
        f.write(time.strftime('%Y-%m-%d %H:%M:%S')+'\n')
        f.write(type(exc).__name__+': '+str(exc)+'\n')
        f.write(traceback.format_exc())

def _error_detail(exc):
    # Never leak secrets; return a compact actionable message to the browser.
    msg=str(exc).strip()
    for secret in (settings.api_key, os.getenv('CLOUD_RU_API_KEY','')):
        if secret: msg=msg.replace(secret,'***')
    return f'{type(exc).__name__}: {msg[:1400]}'

from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException

@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request, exc):
    # FastAPI's default 500 response is just the string "Internal Server Error".
    # Return actionable JSON for server-side errors while preserving normal 4xx behavior.
    if exc.status_code >= 500:
        return JSONResponse(status_code=exc.status_code,content={'detail':str(exc.detail),'build':APP_BUILD_ID})
    return JSONResponse(status_code=exc.status_code,content={'detail':str(exc.detail)})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    _log_unhandled(exc)
    return JSONResponse(status_code=500,content={
        'detail':'Ошибка сервера. Подробности записаны в outputs/server_error.log: '+_error_detail(exc),
        'type':type(exc).__name__,
        'build':APP_BUILD_ID,
    })

def save_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def _save_upload(upload,run_dir):
    suffix=Path(upload.filename or '').suffix.lower()
    if suffix not in {'.pptx','.pdf','.docx','.txt','.md','.csv','.json'}:raise ValueError('Неподдерживаемый файл.')
    data=upload.file.read(20*1024*1024+1)
    if len(data)>20*1024*1024:raise ValueError('Максимум 20 МБ на файл.')
    path=run_dir/(uuid.uuid4().hex+suffix);path.write_bytes(data)
    if suffix in ('.pptx','.docx'):
        with ZipFile(path) as z:
            if len(z.infolist())>8000 or sum(i.file_size for i in z.infolist())>200*1024*1024:raise ValueError('Слишком большой Office-файл после распаковки.')
    return path

def _run(run_id):
    if not re.fullmatch('[a-f0-9]{32}',run_id):raise HTTPException(404,'Run not found')
    path=RUNS/run_id
    if not path.is_dir():raise HTTPException(404,'Run not found')
    return path

def _render_all(run_dir,plan,templates,sources,deadline,image_map=None):
    results=[]
    for item in templates:
        spec=item['spec']
        for variant in VARIANTS:
            stem='presentation_'+item['id']+'_'+variant
            out=run_dir/(stem+'.pptx')
            warning=None
            try:
                if time.monotonic()>=deadline:
                    raise ValueError('Лимит времени генерации исчерпан.')
                render_variant(item['path'],plan,spec,out,variant,item['id'],sources,list((image_map or {}).values()))
                from pptx import Presentation
                check=Presentation(str(out))
                if len(check.slides)!=len(plan['slides']):
                    raise ValueError('После сохранения потерялись слайды.')
            except Exception as exc:
                results.append({'template_id':item['id'],'template_name':item['name'],'variant':variant,
                                'pptx':None,'html':None,'pdf':None,'preview':None,
                                'audit':{'score':0,'issues':[],'status':'render_failed'},
                                'warning':'Не удалось построить этот вариант: '+type(exc).__name__+': '+str(exc)[:320]})
                continue
            # Audit is advisory and must never delete a valid PPTX from the result set.
            try:
                audit=audit_deck(out,plan,spec)
                save_json(run_dir/(stem+'_audit.json'),audit)
                if audit.get('issues'):
                    warning='Аудит обнаружил замечания; файл сохранён и доступен для точечного исправления.'
            except Exception as exc:
                audit={'score':0,'issues':[],'status':'audit_failed','error':type(exc).__name__+': '+str(exc)[:240]}
                warning='Аудит не выполнен полностью; файл сохранён.'
            results.append({'template_id':item['id'],'template_name':item['name'],'variant':variant,
                            'pptx':out.name,'html':None,'pdf':None,'preview':None,
                            'audit':audit,'warning':warning})

    valid=[r for r in results if r.get('pptx')]
    if not valid:
        raise ValueError('Не удалось создать ни одной открываемой презентации.')

    pdf_by_stem={}
    pdf_inputs=[run_dir/r['pptx'] for r in valid if r.get('pptx')]
    try:
        if pdf_inputs:
            remaining=max(12,int(deadline-time.monotonic()))
            if remaining>5:
                pdf_by_stem=export_pdfs_batch(pdf_inputs,run_dir,timeout=max(12,min(90,remaining)))
    except Exception as exc:
        for r in valid:
            r['warning']=((r.get('warning')+' ') if r.get('warning') else '')+'PDF экспорт не создан: '+type(exc).__name__

    for r in valid:
        stem=Path(r['pptx']).stem
        pdf=pdf_by_stem.get(stem)
        if pdf:
            r['pdf']=pdf.name
            if r['variant']=='balanced':
                try:
                    r['preview']=export_preview_png(pdf,run_dir/(stem+'.png')).name
                except Exception as exc:
                    r['warning']=((r.get('warning')+' ') if r.get('warning') else '')+'Превью не создано: '+type(exc).__name__
        try:
            html=export_html(run_dir/r['pptx'],run_dir/(stem+'.html'),pdf)
            r['html']=html.name
        except Exception as exc:
            r['warning']=((r.get('warning')+' ') if r.get('warning') else '')+'HTML экспорт не создан: '+type(exc).__name__
    return results

@app.get('/',response_class=HTMLResponse)
def index():return INDEX_FILE.read_text(encoding='utf-8')
@app.get('/health')
def health():return {'ok':True,'model':settings.model,'build':APP_BUILD_ID}
@app.get('/api/version')
def version():return {'name':'Digital Presentation Designer','version':'7.4.2','build':APP_BUILD_ID,'model':settings.model,'base_url':settings.base_url,'api_timeout':settings.api_timeout,'api_retries':settings.api_retries}
@app.get('/api/templates')
def catalog():return {'builtin':builtin_catalog(),'variants':list(VARIANTS)}
@app.get('/api/diagnostics')
def diagnostics():
    return {'model':settings.model,'base_url':settings.base_url,'api_key_present':bool(settings.api_key),'api_timeout':settings.api_timeout,'api_retries':settings.api_retries,'generation_timeout_seconds':settings.session_seconds,'max_llm_calls':settings.max_llm_calls,'libreoffice':bool(shutil.which('soffice') or shutil.which('libreoffice'))}

@app.post('/api/generate')
def generate(brief:str=Form(''),slides:int=Form(settings.default_slides),template:UploadFile|None=File(None),sources:List[UploadFile]=File(default=[]),include_vk_templates:str=Form('true'),images:List[UploadFile]=File(default=[]),include_images:str=Form('true'),image_mode:str=Form('retrieve')):
    if not brief.strip():raise HTTPException(400,'Укажите тему, цель и аудиторию.')
    if not 3<=slides<=settings.max_slides:raise HTTPException(400,f'Выберите 3–{settings.max_slides} слайдов.')
    if len(sources)>6:raise HTTPException(400,'Не более 6 файлов источников.')
    if len(images)>8:raise HTTPException(400,'Не более 8 изображений.')
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'Дождитесь завершения текущего задания.')
    run_id=uuid.uuid4().hex;run_dir=RUNS/run_id;run_dir.mkdir()
    deadline=time.monotonic()+settings.session_seconds;session=Session(deadline)
    try:
        templates=[]
        vk_mode=include_vk_templates.lower() in ('true','1','yes','on')
        if vk_mode:
            # TЗ demo mode: one semantic deck, three supplied VK templates, three layout variants each.
            templates=[{'id':tid,'name':item['name'],'path':str(builtin_template_path(tid))} for tid,item in BUILTIN_TEMPLATES.items()]
        elif template and template.filename:
            path=_save_upload(template,run_dir)
            if path.suffix!='.pptx':raise ValueError('Шаблон должен быть PPTX.')
            templates.append({'id':'uploaded','name':'Ваш шаблон','path':str(path)})
        else:
            path=build_default_template(run_dir/'base.pptx');templates.append({'id':'ai_base','name':'AI Base','path':str(path)})
        parsed_templates=[]
        for item in templates:
            try:
                item['spec']=parse_template(item['path'])
                parsed_templates.append(item)
            except Exception as exc:
                item['warning']='Шаблон пропущен: не удалось прочитать разметку — '+type(exc).__name__+': '+str(exc)[:180]
        templates=parsed_templates
        if not templates:
            raise ValueError('Не удалось прочитать ни один выбранный PPTX-шаблон.')
        paths=[_save_upload(f,run_dir) for f in sources if f.filename]
        uploaded=extract_source_records(paths,[Path(f.filename).name for f in sources if f.filename])
        # Web research is always attempted first. It is a best-effort enrichment step,
        # not a hard gate: a temporary search/network failure must not prevent a usable
        # presentation when the LLM or uploaded context can still produce one.
        web=research(brief,max_jobs=6,budget_seconds=90,session=session)
        if web.get('warnings'):
            session.artifacts['research_warnings']=web.get('warnings',[])
        evidence=web.get('sources',[])+uploaded
        save_json(run_dir/'sources.json',evidence);save_json(run_dir/'research.json',web)
        save_json(run_dir/'templates.json',templates)
        uploaded_image_items=[]
        image_dir=run_dir/'images'; image_dir.mkdir(exist_ok=True)
        for f in images:
            if not f.filename: continue
            suffix=Path(f.filename).suffix.lower()
            if suffix not in {'.jpg','.jpeg','.png','.webp'}: raise ValueError('Изображения: только JPG, JPEG, PNG или WEBP.')
            raw=f.file.read(12*1024*1024+1)
            if len(raw)>12*1024*1024: raise ValueError('Максимум 12 МБ на изображение.')
            dst=image_dir/(uuid.uuid4().hex+suffix);dst.write_bytes(raw)
            uploaded_image_items.append({'path':str(dst),'title':Path(f.filename).stem,'source':'user_upload','landing_url':''})
        plan=generate_plan(brief,templates[0]['spec'],'',slides,{'sources':evidence},session=session)
        save_json(run_dir/'plan.json',plan)
        image_map={}
        if include_images.lower() in ('true','1','yes','on'):
            try:
                # User-provided images always take priority. Automatic images fill only
                # the remaining suitable slides, so an uploaded figure can never be
                # silently displaced by web search results.
                suitable=[int(s['number']) for s in plan.get('slides',[])
                           if s.get('kind') not in {'title','sources','table','chart','metrics'}]
                for item,slide in zip(uploaded_image_items,suitable):
                    item=dict(item);item['slide']=int(slide);image_map[int(slide)]=item
                auto=collect_images(brief,plan,image_dir,max_images=6,budget_seconds=14,mode=image_mode)
                for item in auto.get('items',[]):
                    n=int(item.get('slide',0))
                    if n and n not in image_map: image_map[n]=item
                image_meta={'items':list(image_map.values()),'provider':auto.get('provider','Openverse/Wikimedia Commons'),'elapsed_seconds':auto.get('elapsed_seconds',0),'uploaded_count':len(uploaded_image_items),'mode':auto.get('mode',image_mode),'warnings':auto.get('warnings',[])}
            except Exception as exc:
                image_meta={'items':uploaded_image_items,'provider':'user_upload','warnings':[type(exc).__name__],'uploaded_count':len(uploaded_image_items)}
                for item,slide in zip(uploaded_image_items,[s['number'] for s in plan.get('slides',[]) if int(s['number'])]):
                    item=dict(item);item['slide']=int(slide);image_map[int(slide)]=item
        else:
            image_meta={'items':uploaded_image_items,'provider':'disabled'}
            for item,slide in zip(uploaded_image_items,[s['number'] for s in plan.get('slides',[])][:len(uploaded_image_items)]):
                item=dict(item);item['slide']=int(slide);image_map[int(slide)]=item
        save_json(run_dir/'images.json',image_meta)
        save_json(run_dir/'generation_settings.json',{'include_vk_templates':vk_mode,'include_images':include_images.lower() in ('true','1','yes','on'),'uploaded_images':len(uploaded_image_items),'image_mode':image_mode.strip().lower()})
        results=_render_all(run_dir,plan,templates,evidence,deadline,image_map)
        save_json(run_dir/'results.json',results)
        return {'run_id':run_id,'plan':plan,'research':{k:web.get(k,[]) for k in ('sources','domains','warnings')},'images':image_meta,'results':results,'usage':session.calls}
    except (ValueError,BadZipFile) as exc:raise HTTPException(422,str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _log_unhandled(exc)
        raise HTTPException(500,'Ошибка сервера: '+_error_detail(exc)) from exc
    finally:
        save_json(run_dir/'generation_trace.json',{'calls':session.calls,'artifacts':session.artifacts})
        LOCK.release()

def _edit(run_id,instruction,audit=False):
    run_dir=_run(run_id)
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'Дождитесь текущего задания.')
    deadline=time.monotonic()+settings.session_seconds;session=Session(deadline)
    try:
        plan=json.loads((run_dir/'plan.json').read_text());sources=json.loads((run_dir/'sources.json').read_text());templates=json.loads((run_dir/'templates.json').read_text())
        image_map={}
        ip=run_dir/'images.json'
        if ip.exists():
            for x in json.loads(ip.read_text()).get('items',[]):
                if x.get('slide') is not None: image_map[int(x['slide'])]=x
        new=repair_plan(plan,instruction,sources,session=session) if audit else revise_plan(plan,instruction,sources,session=session)
        revision_dir=run_dir/('revision_'+uuid.uuid4().hex);revision_dir.mkdir()
        results=_render_all(revision_dir,new,templates,sources,deadline,image_map)
        # Publish every readable PPTX. QA findings are warnings, not blocking gates.
        save_json(revision_dir/'previous_plan.json',plan)
        for r in results:
            for key in ('pptx','pdf','html','preview'):
                if r.get(key):
                    old=run_dir/r[key]
                    if old.exists():shutil.copy2(old,revision_dir/('previous_'+r[key]))
                    shutil.copy2(revision_dir/r[key],old)
        save_json(run_dir/'plan.json',new);save_json(run_dir/'results.json',results)
        return {'run_id':run_id,'plan':new,'results':results}
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _log_unhandled(exc)
        raise HTTPException(500,'Ошибка сервера: '+_error_detail(exc)) from exc
    finally:
        save_json(run_dir/('edit_trace_'+uuid.uuid4().hex+'.json'),{'calls':session.calls,'artifacts':session.artifacts});LOCK.release()

@app.post('/api/revise/{run_id}')
def revise(run_id:str,instruction:str=Form(...)):
    if not instruction.strip():raise HTTPException(400,'Опишите изменение.')
    return _edit(run_id,instruction)

@app.post('/api/repair/{run_id}')
def repair(run_id:str,selected_issues:str=Form('')):
    run_dir=_run(run_id)
    try:
        selected=json.loads(selected_issues or '[]')
    except json.JSONDecodeError as exc:
        raise HTTPException(400,'selected_issues должен быть корректным JSON-массивом.') from exc
    if not isinstance(selected,list) or not selected:
        raise HTTPException(400,'Выберите хотя бы одно замечание для исправления.')
    if len(selected)>60:
        raise HTTPException(400,'Можно выбрать не более 60 замечаний за один проход.')
    # Keep the user-selected scope explicit; deduplicate identical findings before
    # handing them to the semantic repair stage.
    normalized=[]; seen=set()
    for item in selected:
        if not isinstance(item,dict):
            continue
        slide=int(item.get('slide') or 0)
        if slide<1: continue
        problem=str(item.get('problem') or item.get('message') or '').strip()
        fix=str(item.get('fix') or '').strip()
        severity=str(item.get('severity') or 'major')
        key=(slide,problem,fix)
        if not problem or key in seen: continue
        seen.add(key); normalized.append({'slide':slide,'severity':severity if severity in {'critical','major','minor','error','warning'} else 'major','problem':problem[:1200],'fix':fix[:1200]})
    if not normalized:
        raise HTTPException(400,'Не найдено корректных выбранных замечаний.')
    return _edit(run_id,{'audits':normalized,'selected_issue_count':len(normalized)},True)

@app.get('/api/file/{run_id}/{filename}')
def get_file(run_id:str,filename:str):
    path=(_run(run_id)/filename).resolve()
    if path.parent!=_run(run_id).resolve() or not filename.startswith('presentation_') or path.suffix not in ('.pptx','.pdf','.html','.png') or not path.is_file():raise HTTPException(404,'File not found')
    return FileResponse(path)

@app.get('/api/bundle/{run_id}')
def bundle(run_id:str):
    run_dir=_run(run_id)
    pptx=sorted(run_dir.glob('presentation_*.pptx'))
    if not pptx: raise HTTPException(404,'Нет готовых презентаций для скачивания.')
    out=run_dir/'all_presentations.zip'
    with ZipFile(out,'w') as z:
        for p in sorted(run_dir.glob('presentation_*')):
            if p.is_file() and p.suffix in {'.pptx','.pdf','.html'}:
                z.write(p,p.name)
    return FileResponse(out,filename='all_presentations.zip',media_type='application/zip')
