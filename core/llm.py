from __future__ import annotations
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from openai import OpenAI, APIStatusError, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
from pydantic import ValidationError

from .config import settings
from .models import Deck, Slide, SlideBatch, Architecture, Critique, strict_schema
from .quality import quality_issues, source_issues, bibliography, bibliography_slots, harden_plan

PROMPTS = Path(__file__).resolve().parent.parent / 'prompts'
MAX_REQUEST_CHARS = 72_000
SOURCE_CHARS_EACH = 3_200
SOURCE_CHARS_TOTAL = 24_000
BATCH_SIZE = 3
SLIDE_BATCH_FALLBACK_SIZE = 1


def _load_prompt(name):
    return (PROMPTS / name).read_text(encoding='utf-8')


class OutputError(ValueError):
    def __init__(self, message, raw=''):
        super().__init__(message)
        self.raw = raw


class Session:
    def __init__(self, deadline=None):
        self.deadline = deadline or time.monotonic() + getattr(settings, 'session_seconds', 1200)
        self.calls = []
        self.format_repairs = 0
        self.artifacts = {}
        self._preflight_ok = False

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining < 12:
            raise ValueError('Внутренний лимит времени генерации почти исчерпан. Последняя сохранённая версия не изменена.')
        if len(self.calls) >= getattr(settings, 'max_llm_calls', 40):
            raise ValueError('Достигнут безопасный лимит обращений к модели. Уменьшите число повторных правок.')
        return remaining


def _json_object_candidates(text):
    """Return balanced JSON objects found anywhere in model output.

    Qwen/gateways may wrap JSON in prose, Markdown fences, or return two copies.
    We collect all candidates and let Pydantic decide which one is valid.
    """
    raw=(text or '').lstrip('\ufeff \t\r\n')
    candidates=[]
    depth=0; start=None; in_string=False; escaped=False
    for i,ch in enumerate(raw):
        if in_string:
            if escaped: escaped=False
            elif ch=='\\': escaped=True
            elif ch=='"': in_string=False
            continue
        if ch=='"': in_string=True; continue
        if ch=='{':
            if depth==0: start=i
            depth+=1
        elif ch=='}' and depth:
            depth-=1
            if depth==0 and start is not None:
                candidates.append(raw[start:i+1]); start=None
                if len(candidates)>=10: break
    return candidates


def _json_array_candidates(text):
    """Return balanced top-level JSON arrays, mainly for SlideBatch fallback."""
    raw=(text or '').lstrip('\ufeff \t\r\n')
    candidates=[]; depth=0; start=None; in_string=False; escaped=False
    for i,ch in enumerate(raw):
        if in_string:
            if escaped: escaped=False
            elif ch=='\\': escaped=True
            elif ch=='"': in_string=False
            continue
        if ch=='"': in_string=True; continue
        if ch=='[':
            if depth==0: start=i
            depth+=1
        elif ch==']' and depth:
            depth-=1
            if depth==0 and start is not None:
                candidates.append(raw[start:i+1]); start=None
                if len(candidates)>=6: break
    return candidates


def _clean_jsonish_text(raw):
    raw=(raw or '').strip().lstrip('\ufeff')
    raw=re.sub(r'^```(?:json|JSON)?\s*','',raw)
    raw=re.sub(r'\s*```$','',raw)
    raw=re.sub(r'^(?:json|JSON)\s*:\s*','',raw)
    return raw.strip()


def _candidate_payloads(raw,schema):
    """Yield plausible Python payloads without requiring exact surface formatting."""
    cleaned=_clean_jsonish_text(raw)
    chunks=[]
    chunks.extend(_json_object_candidates(cleaned))
    if getattr(schema,'__name__','')=='SlideBatch':
        for arr in _json_array_candidates(cleaned):
            chunks.append('{"slides":'+arr+'}')

    # If the model emitted one quoted JSON string, unwrap it once.
    for obj_text in list(chunks):
        try:
            parsed=json.loads(obj_text)
            if isinstance(parsed,str) and parsed[:1] in '{[':
                if parsed.startswith('{'): chunks.append(parsed)
                elif getattr(schema,'__name__','')=='SlideBatch': chunks.append('{"slides":'+parsed+'}')
        except Exception:
            pass

    seen=set()
    for chunk in chunks:
        if chunk in seen: continue
        seen.add(chunk)
        try:
            value=json.loads(chunk,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            if isinstance(value,dict): yield value
            elif getattr(schema,'__name__','')=='SlideBatch' and isinstance(value,list): yield {'slides':value}
        except Exception:
            # Last-resort Python-literal support for gateways that return single quotes.
            try:
                import ast
                value=ast.literal_eval(chunk)
                if isinstance(value,dict): yield value
                elif getattr(schema,'__name__','')=='SlideBatch' and isinstance(value,list): yield {'slides':value}
            except Exception:
                continue

def _extract_json(text):
    """Strict public helper: exactly one JSON object, no surrounding prose."""
    raw=(text or '').strip()
    if raw.startswith('```') and raw.endswith('```'):
        raw=re.sub(r'^```(?:json|JSON)?\s*','',raw)
        raw=re.sub(r'\s*```$','',raw).strip()
    try:
        value=json.loads(raw,parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except Exception as exc:
        raise OutputError('В диагностическом ответе нет ровно одного валидного JSON-объекта.',text or '') from exc
    if not isinstance(value,dict) or not value:
        raise OutputError('Ожидался непустой JSON-объект.',text or '')
    return value

def _safe_usage(usage):
    try:
        return usage.model_dump() if usage else {}
    except Exception:
        try:
            return dict(usage) if usage else {}
        except Exception:
            return {}


def _compact_sources(sources, per_source=SOURCE_CHARS_EACH, total=SOURCE_CHARS_TOTAL, focus=''):
    """Select compact evidence windows around the user's topic instead of blindly taking page starts."""
    terms = [t for t in re.findall(r'[a-zа-яё0-9]{5,}', (focus or '').lower()) if t not in {'презентация', 'сделать', 'слайдов', 'аудитории'}]
    compact = []
    used = 0
    for source in sources or []:
        text = ' '.join(str(source.get('text', '')).split())
        remaining = total - used
        if remaining < 600:
            break
        budget = min(per_source, remaining)
        if not text:
            excerpt = ''
        else:
            windows = [text[:900]]
            for term in terms[:8]:
                pos = text.lower().find(term)
                if pos >= 0:
                    left = max(0, pos - 550)
                    right = min(len(text), pos + 1600)
                    windows.append(text[left:right])
            joined = ' '.join(windows)
            # Deduplicate overlapping windows while preserving the source wording.
            seen = set(); pieces = []
            for piece in re.split(r'(?<=[.!?])\s+', joined):
                key = piece[:160]
                if key in seen:
                    continue
                seen.add(key); pieces.append(piece)
            excerpt = ' '.join(pieces)[:budget]
        item = {
            'id': source.get('id', ''),
            'kind': source.get('kind', ''),
            'title': source.get('title', ''),
            'url': source.get('url', ''),
            'verified': bool(source.get('verified')),
            'content_type': source.get('content_type', ''),
            'text': excerpt,
        }
        compact.append(item)
        used += len(excerpt)
    return compact


def _compact_template(template_spec):
    """Templates affect rendering, not semantics; never send huge layout catalogs to the LLM."""
    return {
        'slide_size': template_spec.get('slide_size', {}),
        'design_tokens': template_spec.get('design_tokens', {}),
        'slide_count': template_spec.get('slide_count', 0),
        'slide_kinds': [s.get('kind') for s in template_spec.get('slides', [])[:12]],
    }


def _response_format(schema, mode):
    if mode == 'json_object':
        return {'type': 'json_object'}
    return {
        'type': 'json_schema',
        'json_schema': {
            'name': schema.__name__,
            'strict': True,
            'schema': strict_schema(schema),
        },
    }


def _schema_hint(schema):
    """Compact output contract for Qwen. Large JSON schemas make Qwen more likely to omit or invent fields."""
    name = getattr(schema, '__name__', '')
    if name == 'SlideBatch':
        return (
            '{"slides":[{"number":1,"kind":"title|content|two_column|metrics|table|chart|quote|timeline|process|summary|section|sources",'
            '"title":"...","subtitle":"...","points":[],"left_title":"","left_points":[],"right_title":"",'
            '"right_points":[],"metrics":[{"label":"...","value":"...","note":"..."}],'
            '"table":null,"chart":null,"quote":"","timeline":[{"label":"...","detail":"..."}],'
            '"notes":"","source_ids":[],"claims":[{"text":"...","source_id":"...","evidence_quote":"..."}]}]}'
        )
    if name == 'Architecture':
        return '{"story":"...","core_thesis":"...","slides":[{"number":1,"role":"...","key_question":"...","key_message":"...","evidence_needed":[],"source_ids":[],"visual_logic":"..."}]}'
    if name == 'Critique':
        return '{"overall":"pass|repair","issues":[{"slide":1,"severity":"critical|major|minor","problem":"...","fix":"..."}],"global_fixes":[]}'
    return '{"...":"..."}'


def _string_list(value, limit=24):
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r'[\n\r•;]+', value)
        return [p.strip(' -\t') for p in parts if p.strip()][:limit]
    if isinstance(value, (list, tuple)):
        out=[]
        for item in value:
            if isinstance(item, dict):
                for key in ('text','value','detail','content','description','label'):
                    if str(item.get(key,'')).strip():
                        out.append(str(item[key]).strip()); break
            elif item is not None and str(item).strip():
                out.append(str(item).strip())
        return out[:limit]
    return [str(value).strip()][:limit] if str(value).strip() else []


def _alias_dict(data):
    if not isinstance(data, dict):
        return {}
    aliases = {
        'slide_number':'number','slideNo':'number','slide_num':'number','no':'number',
        'heading':'title','headline':'title','subheading':'subtitle','sub_title':'subtitle',
        'bullets':'points','bullet_points':'points','content_blocks':'points','body':'points',
        'left':'left_points','leftPoints':'left_points','leftTitle':'left_title','leftHeading':'left_title',
        'right':'right_points','rightPoints':'right_points','rightTitle':'right_title','rightHeading':'right_title',
        'sourceIds':'source_ids','sources':'source_ids','citations':'claims','evidence':'claims',
        'evidenceQuote':'evidence_quote','sourceId':'source_id','claim':'text','statement':'text',
        'sub-title':'subtitle','slide_type':'kind','layout':'kind','type':'kind',
        'steps':'timeline','process_steps':'timeline','data_table':'table','table_data':'table','chart_data':'chart',
    }
    out={}
    for key,value in data.items():
        nk=aliases.get(key,key)
        if nk not in out:
            out[nk]=value
    return out


def _normalize_kind(value):
    k=str(value or 'content').strip().casefold().replace('—','-').replace('_','-')
    mapping={
        'title':'title','титул':'title','титульный':'title','cover':'title',
        'section':'section','divider':'section','раздел':'section',
        'content':'content','text':'content','body':'content','explanation':'content','основной':'content','текстовый':'content',
        'two-column':'two_column','two columns':'two_column','2-column':'two_column','comparison':'two_column','compare':'two_column','сравнение':'two_column',
        'metrics':'metrics','metric':'metrics','kpi':'metrics','показатели':'metrics',
        'table':'table','таблица':'table',
        'chart':'chart','graph':'chart','diagram':'chart','график':'chart','диаграмма':'chart',
        'quote':'quote','цитата':'quote',
        'timeline':'timeline','chronology':'timeline','хронология':'timeline',
        'process':'process','steps':'process','flow':'process','процесс':'process',
        'summary':'summary','conclusion':'summary','вывод':'summary',
        'sources':'sources','bibliography':'sources','источники':'sources',
    }
    return mapping.get(k, 'content')


def _normalize_metrics(value):
    if isinstance(value, dict):
        value=[value]
    out=[]
    if not isinstance(value, list): return out
    for item in value[:10]:
        if isinstance(item, dict):
            d=_alias_dict(item)
            label=str(d.get('label') or d.get('name') or '').strip()
            val=str(d.get('value') or d.get('number') or '').strip()
            note=str(d.get('note') or d.get('detail') or d.get('description') or '').strip()
            if label and val: out.append({'label':label,'value':val,'note':note})
        elif isinstance(item, str) and ':' in item:
            label,val=item.split(':',1); label=label.strip(); val=val.strip()
            if label and val: out.append({'label':label,'value':val,'note':''})
    return out


def _normalize_table(value):
    if value is None: return None
    if isinstance(value, dict):
        d=_alias_dict(value)
        cols=d.get('columns') or d.get('headers') or d.get('header') or []
        rows=d.get('rows') or d.get('data') or []
    elif isinstance(value, list):
        cols=[]; rows=value
    else:
        return None
    cols=[str(x).strip() for x in _string_list(cols,8) if str(x).strip()]
    if not isinstance(rows,list): return None
    if rows and isinstance(rows[0],dict):
        all_keys=[]
        for r in rows:
            for k in r.keys():
                if k not in all_keys: all_keys.append(k)
        cols=cols or [str(k) for k in all_keys[:5]]
        rows=[[str(r.get(k,'')) for k in all_keys[:len(cols)]] for r in rows]
    else:
        rows=[[str(x) for x in _string_list(r,8)] if not isinstance(r,dict) else [] for r in rows[:12]]
    if not cols or not rows: return None
    width=len(cols)
    fixed=[]
    for row in rows:
        if len(row)<width: row += ['']*(width-len(row))
        fixed.append(row[:width])
    return {'columns':cols[:8],'rows':fixed[:12]}


def _normalize_chart(value):
    if not isinstance(value,dict): return None
    d=_alias_dict(value)
    labels=d.get('labels') or d.get('categories') or d.get('x') or []
    vals=d.get('values') or d.get('data') or d.get('y') or []
    labels=[str(x).strip() for x in _string_list(labels,20)]
    out=[]
    if isinstance(vals,list):
        for x in vals[:10]:
            try: out.append(float(x))
            except (TypeError,ValueError): pass
    typ=str(d.get('type') or 'column').casefold()
    typ={'bar':'bar','column':'column','line':'line','pie':'pie','bar chart':'bar','column chart':'column'}.get(typ,'column')
    unit=str(d.get('unit') or d.get('units') or 'значения').strip()
    if len(labels)>=2 and len(out)==len(labels): return {'type':typ,'labels':labels,'values':out,'unit':unit[:60] or 'значения'}
    return None


def _normalize_timeline(value):
    if isinstance(value,dict): value=list(value.values())
    if not isinstance(value,list): return []
    out=[]
    for item in value[:5]:
        if isinstance(item,dict):
            d=_alias_dict(item)
            label=str(d.get('label') or d.get('date') or d.get('stage') or '').strip()
            detail=str(d.get('detail') or d.get('description') or d.get('text') or '').strip()
            if label or detail: out.append({'label':label or 'Этап','detail':detail or label})
        elif str(item).strip(): out.append({'label':f'Этап {len(out)+1}','detail':str(item).strip()})
    return out


def _normalize_claims(value):
    if isinstance(value,dict): value=list(value.values())
    if not isinstance(value,list): return []
    out=[]
    for item in value[:64]:
        if not isinstance(item,dict): continue
        d=_alias_dict(item)
        text=str(d.get('text') or d.get('claim') or d.get('statement') or '').strip()
        sid=str(d.get('source_id') or '').strip()
        quote=str(d.get('evidence_quote') or d.get('quote') or '').strip()
        if text and sid and quote: out.append({'text':text,'source_id':sid,'evidence_quote':quote})
    return out


def _coerce_slide(raw):
    if not isinstance(raw,dict): raw={}
    d=_alias_dict(raw)
    kind=_normalize_kind(d.get('kind','content'))
    number=d.get('number',1)
    try:
        number=int(re.search(r'\d+',str(number)).group())
    except Exception:
        number=1
    title=str(d.get('title') or d.get('name') or f'Слайд {number}').strip()[:180]
    subtitle=str(d.get('subtitle') or '').strip()[:320]
    points=_string_list(d.get('points'),20)
    left=_string_list(d.get('left_points'),12)
    right=_string_list(d.get('right_points'),12)
    if kind=='two_column' and (not left or not right) and len(points)>=2:
        half=max(1,len(points)//2); left=points[:half]; right=points[half:]
    if kind=='two_column':
        points=[]
    timeline=_normalize_timeline(d.get('timeline'))
    metrics=_normalize_metrics(d.get('metrics'))
    table=_normalize_table(d.get('table'))
    chart=_normalize_chart(d.get('chart'))
    slide={
        'number':number,'kind':kind,'title':title,'subtitle':subtitle,'points':points,
        'left_title':str(d.get('left_title') or '').strip()[:120],
        'left_points':left,'right_title':str(d.get('right_title') or '').strip()[:120],
        'right_points':right,'metrics':metrics,'table':table,'chart':chart,
        'quote':str(d.get('quote') or '').strip(),'timeline':timeline,
        'notes':str(d.get('notes') or '').strip()[:4000],
        'source_ids':[str(x).strip() for x in _string_list(d.get('source_ids'),24) if str(x).strip()],
        'claims':_normalize_claims(d.get('claims')),
    }
    # Clear payloads that conflict with the declared slide kind. This is a common
    # Qwen failure when the model emits a generic object with leftover fields.
    if kind!='two_column': slide['left_points']=[]; slide['right_points']=[]; slide['left_title']=''; slide['right_title']=''
    if kind not in ('chart',): slide['chart']=None
    if kind not in ('table',): slide['table']=None
    if kind not in ('metrics',): slide['metrics']=[]
    if kind not in ('timeline','process'): slide['timeline']=[]
    if kind!='quote': slide['quote']=''
    if kind=='chart' and slide['chart'] is None: slide['kind']='content'
    if kind=='table' and slide['table'] is None: slide['kind']='content'
    if kind=='metrics' and not slide['metrics']: slide['kind']='content'
    if kind in ('timeline','process') and not slide['timeline']: slide['kind']='content'
    if slide['kind']=='two_column' and (not slide['left_points'] or not slide['right_points']):
        slide['kind']='content'
    return slide


def _coerce_payload(schema, obj):
    name=getattr(schema,'__name__','')
    if name=='SlideBatch':
        if isinstance(obj, list): obj={'slides':obj}
        data=_alias_dict(obj)
        slides=data.get('slides')
        if slides is None:
            for key in ('slide_batch','batch','presentation','deck','result','data'):
                candidate=data.get(key)
                if isinstance(candidate,dict) and isinstance(candidate.get('slides'),list):
                    slides=candidate['slides']; break
        if isinstance(slides,dict): slides=list(slides.values())
        if isinstance(slides,list): return {'slides':[_coerce_slide(x) for x in slides]}
        return obj
    if name=='Deck':
        data=_alias_dict(obj)
        if isinstance(data.get('slides'),list):
            data['slides']=[_coerce_slide(x) for x in data['slides']]
        return {k:data.get(k,'') for k in ('title','subtitle','audience','purpose','slides')}
    if name=='Architecture':
        data=_alias_dict(obj)
        raw=data.get('slides') or data.get('outline') or []
        if isinstance(raw,dict): raw=list(raw.values())
        clean=[]
        for item in raw if isinstance(raw,list) else []:
            d=_alias_dict(item)
            try: num=int(re.search(r'\d+',str(d.get('number',len(clean)+1))).group())
            except Exception: num=len(clean)+1
            clean.append({
                'number':num,
                'role':str(d.get('role') or d.get('section') or 'content'),
                'key_question':str(d.get('key_question') or d.get('question') or ''),
                'key_message':str(d.get('key_message') or d.get('message') or ''),
                'evidence_needed':_string_list(d.get('evidence_needed') or d.get('evidence'),8),
                'source_ids':_string_list(d.get('source_ids') or d.get('sources'),8),
                'visual_logic':str(d.get('visual_logic') or d.get('visual') or ''),
            })
        data['slides']=clean
        data['story']=str(data.get('story') or '')
        data['core_thesis']=str(data.get('core_thesis') or '')
        return {'story':data['story'],'core_thesis':data['core_thesis'],'slides':clean}
    if name=='Critique':
        data=_alias_dict(obj)
        raw=data.get('issues') or data.get('findings') or []
        if isinstance(raw,dict): raw=list(raw.values())
        issues=[]
        for item in raw if isinstance(raw,list) else []:
            if not isinstance(item,dict): continue
            d=_alias_dict(item)
            try: slide=int(re.search(r'\d+',str(d.get('slide',0))).group())
            except Exception: slide=0
            sev=str(d.get('severity') or 'major').lower()
            if sev not in ('critical','major','minor'): sev='major'
            issues.append({'slide':slide,'severity':sev,'problem':str(d.get('problem') or d.get('issue') or ''),'fix':str(d.get('fix') or d.get('solution') or '')})
        data['issues']=issues; data['global_fixes']=_string_list(data.get('global_fixes') or data.get('fixes'),8)
        data['overall']='repair' if issues else 'pass'
        return {'overall':data['overall'],'issues':issues,'global_fixes':data['global_fixes']}
    return obj


def _complete(system, payload, temperature=0.2, max_tokens=8000, *, schema=Deck, session=None, stage='generation'):
    session=session or Session()
    if not settings.api_key:
        raise ValueError('CLOUD_RU_API_KEY не задан. Добавьте ключ Cloud.ru в .env и перезапустите сервер.')

    serialized=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    if len(serialized)>MAX_REQUEST_CHARS:
        raise ValueError(f'Слишком большой запрос к модели: {len(serialized):,} символов.')

    schema_hint=_schema_hint(schema)
    instruction=_load_prompt('contract.md')+'\n'+system+'\nОжидаемая форма ответа:\n'+schema_hint
    base_messages=[{'role':'system','content':instruction},{'role':'user','content':serialized}]
    local_repairs=0; api_attempt=0; transient_attempts=0
    current_max_tokens=max(600,min(int(max_tokens),4200))

    while True:
        remaining=session.remaining()
        request_timeout=max(30,min(getattr(settings,'api_timeout',150),int(remaining)-3))
        api_attempt+=1; started=time.monotonic(); messages=list(base_messages)
        if local_repairs:
            messages.append({'role':'user','content':(
                'ПРЕДЫДУЩИЙ ОТВЕТ НЕ ПОДХОДИТ. Повтори тот же ответ, но верни только ОДИН валидный JSON. '
                'Без Markdown, без пояснений, без рассуждений и без текста до/после JSON. '
                'Сохрани все требуемые номера слайдов и обязательные поля. '
                'Локальная ошибка: '+session.artifacts.get(stage+'_validation_error','ошибка JSON')[:1000]
            )})

        request_kwargs={
            'model':settings.model,'messages':messages,'temperature':temperature,
            # Cloud.ru documents max_tokens for its OpenAI-compatible Foundation Models API.
            'max_tokens':current_max_tokens,
            'response_format':{'type':'json_object'},
        }
        if getattr(settings,'disable_thinking',True):
            request_kwargs['extra_body']={'chat_template_kwargs':{'enable_thinking':False}}

        def call_once():
            # Fallback order is intentionally deterministic: remove optional parameters
            # only after the provider rejects them, while keeping the same model and prompt.
            kwargs=dict(request_kwargs)
            attempts=[]
            if 'extra_body' in kwargs:
                attempts.append(dict(kwargs))
                kwargs.pop('extra_body',None)
            attempts.append(dict(kwargs))
            if 'response_format' in kwargs:
                kwargs2=dict(kwargs); kwargs2.pop('response_format',None); attempts.append(kwargs2)
            last=None
            for idx, candidate in enumerate(attempts):
                try:
                    with OpenAI(api_key=settings.api_key,base_url=settings.base_url.rstrip('/'),timeout=request_timeout,max_retries=0) as client:
                        return client.chat.completions.create(**candidate), candidate
                except APIStatusError as exc:
                    last=exc
                    if exc.status_code not in (400,422):
                        raise
                    continue
            if last:
                raise last
            raise RuntimeError('Cloud.ru: не удалось выполнить запрос к модели.')

        try:
            response, used_kwargs = call_once()
        except APIStatusError as exc:
            code=exc.status_code; elapsed=round(time.monotonic()-started,2)
            session.calls.append({'stage':stage,'attempt':api_attempt,'http_status':code,'seconds':elapsed})
            if code in (408,409,429,500,502,503,504) and transient_attempts<getattr(settings,'api_retries',2):
                transient_attempts+=1; time.sleep(min(2*(2**(transient_attempts-1)),6)); continue
            messages_={401:'API-ключ Cloud.ru недействителен или не активирован (HTTP 401).',403:f'У API-ключа нет доступа к модели {settings.model} (HTTP 403).',404:f'Cloud.ru не нашёл модель/endpoint {settings.model} (HTTP 404).',429:'Cloud.ru временно ограничил частоту запросов (HTTP 429).',400:'Cloud.ru отклонил параметры запроса (HTTP 400).',422:'Cloud.ru отклонил структуру запроса (HTTP 422).'}
            raise ValueError(messages_.get(code,f'Cloud.ru вернул HTTP {code}.')) from exc
        except (APITimeoutError,APIConnectionError,RateLimitError,InternalServerError) as exc:
            elapsed=round(time.monotonic()-started,2); kind=type(exc).__name__
            session.calls.append({'stage':stage,'attempt':api_attempt,'error':kind,'seconds':elapsed})
            if transient_attempts<getattr(settings,'api_retries',2):
                transient_attempts+=1; time.sleep(min(2*(2**(transient_attempts-1)),6)); continue
            raise ValueError(f'Cloud.ru не вернул ответ после {api_attempt} попыток: {kind}.') from exc
        except Exception as exc:
            session.calls.append({'stage':stage,'attempt':api_attempt,'error':type(exc).__name__})
            raise ValueError(f'Ошибка обращения к LLM: {type(exc).__name__}: {exc}') from exc

        # Record the exact provider-compatible request shape used on the successful call.
        request_kwargs = used_kwargs

        choices=getattr(response,'choices',None) or []
        if not choices: raise OutputError('Cloud.ru вернул ответ без choices.','')
        choice=choices[0]; message=getattr(choice,'message',None)
        raw=(getattr(message,'content',None) or '').strip()
        # Some OpenAI-compatible gateways expose final content in a secondary field.
        if not raw:
            raw=(getattr(message,'reasoning_content',None) or getattr(message,'refusal',None) or '').strip()
        finish_reason=getattr(choice,'finish_reason',None)
        session.calls.append({'stage':stage,'attempt':api_attempt,'seconds':round(time.monotonic()-started,2),'finish_reason':finish_reason,'usage':_safe_usage(getattr(response,'usage',None)),'prompt_sha256':hashlib.sha256(instruction.encode()).hexdigest(),'response_format':request_kwargs.get('response_format',{}),'max_tokens':current_max_tokens})
        session.artifacts[f'{len(session.calls):02d}_{stage}_raw']=raw[:18000]

        if finish_reason=='length':
            if current_max_tokens<4200:
                current_max_tokens=min(4200,int(current_max_tokens*1.3)); continue
            raise OutputError('Ответ модели обрезан по лимиту длины.',raw)
        if raw:
            validation_errors=[]
            for obj in _candidate_payloads(raw,schema):
                try:
                    coerced=_coerce_payload(schema,obj)
                    return schema.model_validate(coerced).model_dump()
                except ValidationError as ve:
                    validation_errors.append(str(ve)[:1400])
                except Exception as exc:
                    validation_errors.append(str(exc)[:800])
            if validation_errors:
                session.artifacts[stage+'_validation_error']='; '.join(validation_errors[:2])
            else:
                session.artifacts[stage+'_validation_error']='В ответе не найдено валидного JSON после извлечения объектов/массивов.'
        else:
            session.artifacts[stage+'_validation_error']='Модель вернула пустой/нераспознанный ответ.'

        local_repairs+=1; session.format_repairs+=1
        if local_repairs<=2:
            continue

        # Last-resort deterministic recovery for slide batches. The generator must
        # not fail just because Qwen returned malformed JSON after a few retries.
        # Build the requested slides directly from the already-verified web evidence.
        if getattr(schema,'__name__','') == 'SlideBatch':
            try:
                required = [int(x) for x in (payload.get('required_slide_numbers') or [])]
                architecture = payload.get('architecture') or {}
                brief = str(payload.get('brief') or '')
                sources_payload = payload.get('sources') or []
                if required and sources_payload:
                    fallback = _fallback_batch(required, brief, architecture, sources_payload)
                    return SlideBatch.model_validate(fallback).model_dump()
            except Exception as exc:
                session.artifacts[stage+'_deterministic_fallback_error']=type(exc).__name__+': '+str(exc)[:500]

        raise OutputError('Ответ модели не удалось привести к рабочему JSON-контракту после автоматического восстановления: '+session.artifacts[stage+'_validation_error'][:1200],raw)


def _fallback_architecture(brief,sources,count):
    slides=[]; web=[s for s in sources if s.get('kind')=='web' and s.get('verified')]
    topic=brief.strip()[:180] or 'Заданная тема'
    roles=['title','problem','context','comparison','process','evidence','implications','case','recommendations','summary','sources']
    for i in range(count):
        src=web[i%len(web)] if web else None
        slides.append({'number':i+1,'role':roles[i%len(roles)],'key_question':f'Что важно понять на слайде {i+1}?','key_message':topic if i==0 else (src.get('title') if src else topic),'evidence_needed':['проверенный веб-источник'] if src else [],'source_ids':[src['id']] if src else [],'visual_logic':'Объясняющий или сравнительный блок'})
    return {'story':f'От постановки задачи к проверенным выводам по теме: {topic}.','core_thesis':'Содержание строится на проверяемых веб-источниках и затем переносится в редактируемый шаблон.','slides':slides}


def _fallback_batch(numbers,brief=None,architecture=None,sources=None):
    # Backward-compatible call shape retained for older offline tests/helpers:
    # _fallback_batch(brief, {'sources': [...]}, numbers).
    if sources is None and isinstance(brief,dict) and isinstance(architecture,(list,tuple)):
        legacy_brief=numbers; legacy_payload=brief; legacy_numbers=list(architecture)
        numbers=legacy_numbers; brief=str(legacy_brief); sources=list(legacy_payload.get('sources',[]) or []); architecture={'slides':legacy_payload.get('slides',[]) or []}
    brief=str(brief or '')
    architecture=architecture or {}
    sources=sources or []
    usable=[s for s in sources if s.get('text') and (
        (s.get('kind')=='web' and s.get('verified')) or s.get('kind')=='upload'
    )]
    out=[]
    for n in numbers:
        outline=next((s for s in architecture.get('slides',[]) if int(s.get('number',0))==n),{})
        src=usable[(n-1)%len(usable)] if usable else None
        raw=' '.join(str(src.get('text','')).split()) if src else ''
        topic=str(outline.get('key_message') or '').strip() or (brief.strip()[:220] if brief.strip() else 'Заданная тема')
        sentences=[s.strip() for s in re.split(r'(?<=[.!?])\s+',raw) if len(re.findall(r'[\wА-Яа-яЁё-]+',s))>=10]
        blocks=[]
        for sentence in sentences:
            ws=re.findall(r'[\wА-Яа-яЁё-]+',sentence)
            if 18<=len(ws)<=35: blocks.append(sentence)
            elif len(ws)>35: blocks.append(' '.join(ws[:35])+'.')
            if len(blocks)>=2: break
        if len(blocks)<2:
            if raw:
                words=re.findall(r'[\wА-Яа-яЁё-]+',raw)
                if words:
                    blocks=[(' '.join(words[:30])+'.').strip(),(' '.join(words[30:60])+'.').strip()]
                    blocks=[b for b in blocks if len(re.findall(r'[\wА-Яа-яЁё-]+',b))>=8]
            if len(blocks)<2:
                blocks=[
                    f'{topic}. Слайд раскрывает ключевую мысль через объяснение механизма, контекста и практического следствия для аудитории.',
                    f'Показанный подход связывает тему с последовательностью действий и помогает понять, какие факторы определяют результат и где возникают основные ограничения.'
                ]
        kind='title' if n==1 else ('two_column' if n==3 else ('summary' if n==numbers[-1] else ('process' if n==4 else 'content')))
        sid=src.get('id') if src else ''
        slide={'number':n,'kind':kind,'title':str(outline.get('key_message') or (src.get('title') if src else topic) or f'Слайд {n}')[:160],
               'subtitle':'','points':blocks[:2],'left_title':'Суть','left_points':[blocks[0]],'right_title':'Следствие','right_points':[blocks[1]],
               'metrics':[],'table':None,'chart':None,'quote':'','timeline':[{'label':'Шаг 1','detail':blocks[0]},{'label':'Шаг 2','detail':blocks[1]}] if kind=='process' else [],
               'notes':'','source_ids':[sid] if sid else [],'claims':[]}
        if kind=='title': slide['points']=[]; slide['left_points']=[]; slide['right_points']=[]; slide['left_title']=''; slide['right_title']=''; slide['timeline']=[]
        if kind!='two_column': slide['left_points']=[];slide['right_points']=[];slide['left_title']='';slide['right_title']=''
        out.append(slide)
    return {'slides':out}

def _normalize_plan(plan, requested):
    validated = Deck.model_validate(plan).model_dump()
    if len(validated['slides']) != requested:
        raise ValueError(f'Требуется {requested} слайдов, получено {len(validated["slides"])}.')
    if [s['number'] for s in validated['slides']] != list(range(1, requested + 1)):
        raise ValueError('Номера слайдов должны идти последовательно, начиная с 1.')
    return validated


def _validate_batch(batch, numbers):
    # Be tolerant about the model returning a Deck or extra slides; keep only the
    # explicitly requested numbered slides. Local validation remains authoritative.
    normalized = _coerce_payload(SlideBatch, batch)
    validated = SlideBatch.model_validate(normalized).model_dump()
    expected=set(numbers)
    by_num={s['number']:s for s in validated['slides']}
    missing=expected-set(by_num)
    if missing:
        raise ValueError(f'Модель не вернула слайды: {sorted(missing)}.')
    return {n:by_num[n] for n in numbers}


def _sources_for_model(sources, focus=''):
    return _compact_sources(sources, focus=focus)


def _repair_selected(plan, selected, issues, brief, sources, architecture, session, stage='targeted_repair'):
    replacements={}
    source_ctx=_sources_for_model(sources,brief)
    normalized_issues=_issue_dicts(issues)

    def repair_chunk(chunk):
        chunk_numbers=[s['number'] for s in chunk]
        chunk_issues=[x for x in normalized_issues if int(x.get('slide',0)) in chunk_numbers or not int(x.get('slide',0))]
        prompt=_load_prompt('repair_deck_strict.md')+'\nВерни SlideBatch только для указанных номеров: '+', '.join(map(str,chunk_numbers))+'.'
        try:
            fixed=_complete(
                prompt,
                {'brief':brief,'architecture':architecture,'slides_to_replace':chunk,'issues':chunk_issues,'sources':source_ctx,'required_slide_numbers':chunk_numbers},
                0.05,3200,schema=SlideBatch,session=session,stage=stage
            )
            replacements.update(_validate_batch(fixed,chunk_numbers))
        except (OutputError,ValidationError,ValueError) as exc:
            if len(chunk)>1:
                for single in chunk:
                    repair_chunk([single])
            else:
                raise ValueError(f'Не удалось восстановить слайд {chunk_numbers[0]}: {exc}') from exc

    for i in range(0,len(selected),BATCH_SIZE):
        repair_chunk(selected[i:i+BATCH_SIZE])
    if set(replacements)!=set(s['number'] for s in selected):
        raise ValueError('Редактор не вернул все требуемые слайды.')
    candidate={**plan,'slides':[replacements.get(s['number'],s) for s in plan['slides']]}
    return harden_plan(candidate,sources)

def _issue_dicts(issues):
    result=[]
    for issue in issues or []:
        if isinstance(issue, dict):
            result.append(issue); continue
        text=str(issue)
        m=re.search(r'Слайд (\d+):', text)
        result.append({
            'slide': int(m.group(1)) if m else 0,
            'severity': 'major',
            'problem': text,
            'fix': 'Исправь указанную проблему, сохрани проверяемые факты и привяжи каждый существенный тезис к проверенному веб-источнику.'
        })
    return result


def _repair_quality_until_pass(plan, brief, sources, architecture, session, requested):
    current=plan
    current = harden_plan(current, sources)
    for round_no in range(1,3):
        issues=quality_issues(current, requested)+source_issues(current, sources)
        if not issues:
            return current
        issue_objs=_issue_dicts(issues)
        slide_numbers=sorted({int(x['slide']) for x in issue_objs if 1 <= int(x.get('slide',0)) <= requested})
        if not slide_numbers:
            slide_numbers=[s['number'] for s in current['slides'] if s['kind'] not in ('sources','section')]
        selected=[s for s in current['slides'] if s['number'] in slide_numbers and s['kind']!='sources']
        if not selected:
            return current
        current=_repair_selected(current, selected, issue_objs, brief, sources, architecture, session, stage=f'quality_repair_{round_no}')
        current=_normalize_plan(current, requested)
        session.artifacts[f'quality_round_{round_no}_issues_before']=issues
    return current


def verify_final_plan(plan, sources, session):
    source_ctx = _sources_for_model(sources, plan.get('purpose', ''))
    review = _complete(
        _load_prompt('verify_facts.md'),
        {'plan': plan, 'sources': source_ctx},
        0.02, 2800, schema=Critique, session=session, stage='final_fact_check'
    )
    session.artifacts['final_fact_review'] = review
    serious = [i for i in review['issues'] if i['severity'] in ('critical', 'major')]
    if not serious:
        return plan
    numbers = sorted({i['slide'] for i in serious})
    selected = [s for s in plan['slides'] if s['number'] in numbers and s['kind'] != 'sources']
    if not selected:
        raise ValueError('Финальная проверка обнаружила неподтверждённые факты в финальной версии.')
    fixed = _repair_selected(plan, selected, serious, plan.get('purpose', ''), sources, {}, session, stage='fact_repair')
    session.artifacts['fact_repaired_candidate'] = fixed
    return fixed


def generate_plan(brief,template_spec,source_text,requested_slides,research_text='',*,session=None):
    """Generate a usable deck. Content QA is advisory; only structural/API failures block output."""
    session=session or Session(); requested=int(requested_slides)
    if not 3<=requested<=settings.max_slides:
        raise ValueError(f'Выберите от 3 до {settings.max_slides} слайдов.')
    sources=_evidence(source_text,research_text)
    web_sources=[s for s in sources if s.get('kind')=='web' and s.get('verified') and s.get('text')]
    upload_sources=[s for s in sources if s.get('kind')=='upload' and s.get('text')]
    if web_sources:
        source_mode='web_verified'
    elif upload_sources:
        source_mode='uploaded_context_fallback'
        session.artifacts['source_mode_warning']='Веб-источники временно недоступны; использован загруженный контекст.'
    else:
        source_mode='model_knowledge_fallback'
        session.artifacts['source_mode_warning']='Веб-источники временно недоступны; генерация продолжена на знаниях модели без принудительных точных числовых утверждений.'

    refs=bool(re.search(r'источник|библиограф|литератур|гост|references|sources',brief,re.I))
    ref_slots=bibliography_slots(sources,requested) if refs and sources else 0
    content_count=requested-ref_slots
    source_ctx=_sources_for_model(sources,brief)
    evidence={'brief':brief.strip(),'requested_slides':content_count,'sources':source_ctx,'bibliography_slots':0,'bibliography_appended_by_server':ref_slots,
              'template_mode':'render_only; semantic generation is template-independent','source_mode':source_mode,
              'supported_slide_kinds':['title','content','two_column','metrics','table','chart','quote','timeline','process','summary']}

    try:
        architecture=_complete(_load_prompt('architect_deck.md'),evidence,0.05,2200,schema=Architecture,session=session,stage='architecture')
    except Exception as exc:
        architecture=_fallback_architecture(brief,sources,content_count)
        session.artifacts['architecture_fallback']=str(exc)[:800]
    session.artifacts['architecture']=architecture

    slides=[]
    for start_no in range(1,content_count+1,BATCH_SIZE):
        end_no=min(content_count,start_no+BATCH_SIZE-1); nums=list(range(start_no,end_no+1))
        outline=[s for s in architecture.get('slides',[]) if int(s.get('number',0)) in nums]
        batch_prompt=_load_prompt('write_deck.md')+'\n\nВерни только один JSON-объект SlideBatch. Не добавляй Markdown или пояснения. Используй только требуемые номера слайдов. Содержание делай достаточно подробным для готовой презентации. Источники являются главным приоритетом; если source_mode != web_verified, не выдумывай точные цифры, даты, проценты и цитаты и не подставляй URL/служебные фразы вместо содержания. source_mode={{SOURCE_MODE}}'.replace('{{SOURCE_MODE}}',source_mode)
        payload={'brief':brief.strip(),'requested_total_slides':content_count,'required_slide_numbers':nums,'architecture':{'story':architecture['story'],'core_thesis':architecture['core_thesis'],'slides':outline},'sources':source_ctx,'template_mode':'render_only','source_mode':source_mode}
        try:
            batch=_complete(batch_prompt,payload,0.12,3000,schema=SlideBatch,session=session,stage=f'write_{start_no}_{end_no}')
            clean=_validate_batch(batch,nums)
        except Exception as exc:
            session.artifacts[f'write_{start_no}_{end_no}_fallback']=str(exc)[:1200]
            clean=_validate_batch(_fallback_batch(nums,brief,architecture,sources),nums)
        slides.extend(clean.values())

    slides=sorted(slides,key=lambda s:s['number'])
    if len(slides)!=content_count:
        # Last-resort deterministic completion so the user still gets the requested deck.
        missing=[n for n in range(1,content_count+1) if n not in {s['number'] for s in slides}]
        if missing:
            slides.extend(_validate_batch(_fallback_batch(missing,brief,architecture,sources),missing).values())
    slides=sorted(slides,key=lambda s:s['number'])[:content_count]
    first=slides[0]
    plan=Deck(title=first['title'],subtitle=first.get('subtitle','') or brief.strip()[:320],audience='',purpose=brief.strip()[:1000],slides=slides).model_dump()
    plan=harden_plan(plan,sources); plan=_normalize_plan(plan,content_count)
    session.artifacts['candidate']=plan

    # Advisory QA only. It is recorded and returned to diagnostics; it never blocks generation.
    try:
        session.artifacts['final_checks']=quality_issues(plan,content_count)+source_issues(plan,sources)
    except Exception as exc:
        session.artifacts['final_checks_error']=str(exc)[:800]
    if refs:
        for i in range(ref_slots):
            plan['slides'].append(Slide(number=content_count+i+1,kind='sources',title='Источники').model_dump())
        plan=bibliography(plan,sources,ref_slots)
    return plan

def revise_plan(plan, instruction, sources=None, *, session=None):
    session = session or Session()
    evidence = sources or []
    source_ctx = _sources_for_model(evidence, plan.get('purpose', ''))
    editable = [s for s in plan['slides'] if s['kind'] != 'sources']
    revised_map = {}
    for start in range(0, len(editable), BATCH_SIZE):
        chunk = editable[start:start + BATCH_SIZE]
        numbers = [s['number'] for s in chunk]
        prompt = _load_prompt('revise_deck.md') + '\nВерни только SlideBatch с номерами: ' + ', '.join(map(str, numbers)) + '.'
        try:
            batch = _complete(
                prompt,
                {'instruction': instruction, 'plan_batch': chunk, 'sources': source_ctx, 'required_slide_numbers': numbers},
                0.12, 4200, schema=SlideBatch, session=session, stage=f'revision_{numbers[0]}_{numbers[-1]}'
            )
            revised_map.update(_validate_batch(batch, numbers))
        except Exception as exc:
            session.artifacts[f'revision_{numbers[0]}_{numbers[-1]}_fallback']=str(exc)[:900]
            revised_map.update({s['number']: s for s in chunk})
    revised = {**plan, 'slides': [revised_map.get(s['number'], s) for s in plan['slides']]}
    revised = harden_plan(revised, evidence)
    revised = _normalize_plan(revised, len(plan['slides']))
    slots = sum(s['kind'] == 'sources' for s in plan['slides'])
    if slots:
        revised = bibliography(revised, evidence, slots)
    try:
        session.artifacts['revision_checks']=quality_issues(revised, len(plan['slides'])) + source_issues(revised, evidence)
    except Exception as exc:
        session.artifacts['revision_checks_error']=str(exc)[:800]
    return revised

def repair_plan(plan, audit, sources=None, *, session=None):
    """Repair only the slides explicitly selected by the user.

    This endpoint is intentionally targeted: unselected slides are preserved byte-for-byte
    at the plan level and are not sent through the semantic revision loop.
    """
    session=session or Session()
    evidence=sources or []
    audit_items=audit.get('audits',[]) if isinstance(audit,dict) else audit
    issue_objs=_issue_dicts(audit_items)
    slide_numbers=sorted({int(x.get('slide',0)) for x in issue_objs if 1<=int(x.get('slide',0))<=len(plan.get('slides',[]))})
    if not slide_numbers:
        raise ValueError('В выбранных замечаниях нет валидных номеров слайдов.')
    selected=[s for s in plan['slides'] if s['number'] in slide_numbers and s['kind']!='sources']
    if not selected:
        raise ValueError('Выбранные замечания относятся только к слайдам источников, которые нельзя автоматически редактировать.')
    # Minimal architecture context derived from the existing plan; it is only guidance
    # for the targeted repair and does not trigger a new planning pass.
    architecture={
        'story':plan.get('subtitle','') or plan.get('purpose',''),
        'core_thesis':plan.get('purpose',''),
        'slides':[{'number':s['number'],'role':s['kind'],'key_question':'','key_message':s['title'],'evidence_needed':[],'source_ids':s.get('source_ids',[]),'visual_logic':s['kind']} for s in selected],
    }
    fixed=_repair_selected(plan,selected,issue_objs,plan.get('purpose',''),evidence,architecture,session,stage='selected_audit_repair')
    fixed=_normalize_plan(fixed,len(plan['slides']))
    slots=sum(s['kind']=='sources' for s in plan['slides'])
    if slots:
        fixed=bibliography(fixed,evidence,slots)
    session.artifacts['selected_repair_slides']=slide_numbers
    session.artifacts['selected_repair_issues']=issue_objs
    try:
        session.artifacts['selected_repair_checks']=quality_issues(fixed,len(plan['slides']))+source_issues(fixed,evidence)
    except Exception as exc:
        session.artifacts['selected_repair_checks_error']=str(exc)[:800]
    return fixed


def _evidence(source_text, research_text):
    if isinstance(research_text, dict):
        data = research_text
    else:
        try:
            data = json.loads(research_text or '{}')
        except ValueError:
            data = {}
    sources = list(data.get('sources', []))
    if source_text and not any(s.get('kind') == 'upload' for s in sources):
        sources.insert(0, {
            'id': 'U1', 'kind': 'upload', 'title': 'Материалы пользователя', 'text': source_text,
            'url': '', 'accessed_at': '', 'verified': False,
        })
    return sources
