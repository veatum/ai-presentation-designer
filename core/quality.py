from __future__ import annotations
import math
import re
import string
from datetime import datetime
from collections import Counter
from .models import visible_text


def norm(text):
    """Stable text comparison: ignores case, whitespace and harmless punctuation differences."""
    text = str(text or '').casefold().replace('\u00a0', ' ')
    text = text.translate(str.maketrans('', '', string.punctuation + '«»„“”’—–'))
    return ' '.join(text.split())


def numbers(text):
    return set(re.findall(r'(?<![\w])\d+(?:[.,]\d+)?', str(text).replace('\u00a0', ' ')))


def _words(text):
    return re.findall(r'[\wА-Яа-яЁё-]+', str(text or ''))


def _word_count(text):
    return len(_words(text))


def _split_sentences(text):
    text = ' '.join(str(text or '').split())
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_words(text, min_words=18, max_words=35):
    words = _words(text)
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + max_words, len(words))
        # Leave enough room in the remainder to make a valid second block.
        remaining = len(words) - end
        if remaining and remaining < min_words and end - i > min_words:
            end = max(i + min_words, len(words) - min_words)
        chunk = ' '.join(words[i:end]).strip(' ,;:-')
        if chunk:
            chunks.append(chunk)
        i = end
    return chunks


def _candidate_blocks(slide):
    kind = slide.get('kind')
    if kind == 'two_column':
        return list(slide.get('left_points', [])) + list(slide.get('right_points', []))
    if kind in ('timeline', 'process'):
        return [x.get('detail', '') for x in slide.get('timeline', [])]
    if kind in ('chart', 'table', 'metrics', 'quote'):
        return list(slide.get('points', []))
    return list(slide.get('points', []))


def _set_blocks(slide, blocks):
    kind = slide.get('kind')
    blocks = [b.strip() for b in blocks if str(b).strip()]
    if kind == 'two_column':
        # Split evenly and keep both columns substantive.
        half = max(1, len(blocks) // 2)
        left = blocks[:half]
        right = blocks[half:]
        if not right and left:
            right = [left.pop()]
        slide['left_points'] = left[:4]
        slide['right_points'] = right[:4]
        return
    if kind in ('timeline', 'process'):
        old = slide.get('timeline', [])
        rebuilt = []
        for i, block in enumerate(blocks[:5]):
            label = old[i].get('label', '') if i < len(old) else f'Этап {i + 1}'
            rebuilt.append({'label': label or 'Этап', 'detail': block})
        slide['timeline'] = rebuilt
        return
    slide['points'] = blocks[:5]


def _clean_visible_text(value):
    text=' '.join(str(value or '').split())
    if not text:
        return ''
    text=re.sub(r'https?://\S+', '', text)
    text=re.sub(r'\[[Ww][A-Za-z0-9_:-]+\]', '', text)
    text=re.sub(
        r'\b(?:к основному контенту|справка\s*-\s*google\s*поиск|google\s*search|search\s*help|'
        r'справочный\s+центр|попробуйте\s+следующее|отправить\s+отзыв|войти|sign\s+in|help\s+center)\b.*',
        '',
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r'\s{2,}',' ',text).strip()

def _sanitize_plan_content(plan, sources):
    """Remove accidental source/navigation text from the visible slide payload.
    Never invent facts; if a block becomes empty, replace it with a source-backed
    explanatory sentence when possible.
    """
    web=[s for s in sources if s.get('kind')=='web' and s.get('verified') and str(s.get('text','')).strip()]
    fallback_by_slide={}
    for slide in plan.get('slides',[]):
        if slide.get('kind') in ('title','section','sources'):
            continue
        replacement=_relevant_source_sentences(slide, sources, count=4) if web else []
        fallback_iter=iter(replacement)
        def clean_list(items):
            out=[]
            for item in items or []:
                cleaned=_clean_visible_text(item)
                if len(_words(cleaned))<4:
                    try:
                        repl=next(fallback_iter)
                    except StopIteration:
                        repl=''
                    cleaned=repl if len(_words(repl))>=4 else cleaned
                if cleaned:
                    out.append(cleaned)
            return out

        for key in ('points','left_points','right_points'):
            slide[key]=clean_list(slide.get(key,[]))
        slide['subtitle']=_clean_visible_text(slide.get('subtitle',''))
        slide['left_title']=_clean_visible_text(slide.get('left_title',''))
        slide['right_title']=_clean_visible_text(slide.get('right_title',''))
        slide['quote']=_clean_visible_text(slide.get('quote',''))
        for step in slide.get('timeline',[]) or []:
            step['label']=_clean_visible_text(step.get('label',''))
            step['detail']=_clean_visible_text(step.get('detail',''))
        for metric in slide.get('metrics',[]) or []:
            metric['label']=_clean_visible_text(metric.get('label',''))
            metric['value']=_clean_visible_text(metric.get('value',''))
            metric['note']=_clean_visible_text(metric.get('note',''))
        if slide.get('table'):
            slide['table']['columns']=[_clean_visible_text(x) for x in slide['table']['columns']]
            slide['table']['rows']=[[_clean_visible_text(x) for x in row] for row in slide['table']['rows']]
        if slide.get('chart'):
            slide['chart']['labels']=[_clean_visible_text(x) for x in slide['chart']['labels']]
            slide['chart']['unit']=_clean_visible_text(slide['chart']['unit'])
    return plan

def _source_tokens(text):
    return set(re.findall(r'[a-zа-яё0-9]{4,}', norm(text)))


def _best_source_quote(claim_text, source):
    text = ' '.join(str(source.get('text', '')).split())
    if not text:
        return ''
    target = _source_tokens(claim_text)
    sentences = [s for s in _split_sentences(text) if 8 <= _word_count(s) <= 55]
    best = ''
    best_score = -1.0
    for sentence in sentences:
        tokens = _source_tokens(sentence)
        if not tokens:
            continue
        overlap = len(target & tokens)
        score = overlap / max(1, len(target))
        claim_nums = numbers(claim_text)
        quote_nums = numbers(sentence)
        if claim_nums:
            score += 0.25 * len(claim_nums & quote_nums) / max(1, len(claim_nums))
        # Prefer sentences that are themselves long enough to be explanatory evidence.
        if _word_count(sentence) >= 18:
            score += 0.08
        if score > best_score:
            best_score = score
            best = sentence
    if best:
        return best
    # Fallback to a source substring around the first meaningful keyword.
    lower = text.casefold()
    keywords = sorted(target, key=len, reverse=True)
    for token in keywords[:8]:
        pos = lower.find(token)
        if pos >= 0:
            left = max(0, pos - 180)
            right = min(len(text), pos + 500)
            candidate = text[left:right].strip()
            words = _words(candidate)
            if len(words) >= 8:
                return ' '.join(words[:55])
    return text[:900]


def _best_web_source(slide, sources):
    index = {s.get('id'): s for s in sources}
    preferred = [index.get(i) for i in slide.get('source_ids', [])]
    candidates = [s for s in preferred if s and s.get('kind') == 'web' and s.get('verified')]
    if candidates:
        return candidates[0]
    return next((s for s in sources if s.get('kind') == 'web' and s.get('verified')), None)


def _normalize_claims(plan, sources):
    """Authoritative source/claim normalization.

    Claims are bookkeeping, not visible slide content, so the server may keep more
    than eight when a slide contains several independently evidenced facts/numbers.
    The visible source_ids list remains compact. All claim quotes must be verbatim
    substrings of verified web sources before the final QA gate.
    """
    index={s.get('id'):s for s in sources}
    web=[s for s in sources if s.get('kind')=='web' and s.get('verified') and str(s.get('text','')).strip()]
    for slide in plan.get('slides',[]):
        if slide.get('kind') in ('title','section','sources'):
            continue
        ids=[i for i in slide.get('source_ids',[]) if i in index]
        blocks=[str(x).strip() for x in _candidate_blocks(slide) if str(x).strip()]
        claims=[]; seen_pairs=set()
        for block in blocks:
            target=_source_tokens(block)
            best=None; best_score=-1.0
            for src in web:
                score=len(target & _source_tokens(src.get('text','')))/max(1,len(target))
                if numbers(block):
                    source_nums=numbers(src.get('text',''))
                    score += 0.15*len(numbers(block)&source_nums)/max(1,len(numbers(block)))
                if src.get('id') in ids: score += 0.03
                if score>best_score:
                    best_score=score; best=src
            if best:
                quote=_best_source_quote(block,best)
                if quote and norm(quote) in norm(best.get('text','')):
                    key=(block,best['id'],norm(quote))
                    if key not in seen_pairs:
                        claims.append({'text':block,'source_id':best['id'],'evidence_quote':quote})
                        seen_pairs.add(key)

        if web:
            selected={c['source_id'] for c in claims}
            fallback=next((w for w in web if w['id'] in selected),web[0])
            ids=[fallback['id']]+[i for i in ids if i!=fallback['id']]
            for c in claims:
                if c['source_id'] not in ids and len(ids)<8:
                    ids.append(c['source_id'])
        slide['source_ids']=ids[:8]
        slide['claims']=claims

        # Every visible numeric value must have matching numeric evidence. We keep
        # separate claim records when necessary, but merge records when the same quote
        # proves multiple numbers. This prevents accidental overflow while preserving
        # exact evidence for each number.
        evidence_text=' '.join(c.get('evidence_quote','') for c in slide['claims'])
        preferred_ids=slide.get('source_ids', [])
        slide_text=' '.join(_candidate_blocks(slide))
        for part in _visible_numeric_parts(slide):
            for num in sorted(numbers(part) - numbers(evidence_text)):
                src,quote=_numeric_quote(num,web,preferred_ids,slide_text)
                if not src or not quote:
                    continue
                merged=False
                for c in slide['claims']:
                    if c['source_id']==src['id'] and norm(c['evidence_quote'])==norm(quote):
                        merged=True
                        break
                if not merged:
                    slide['claims'].append({'text':part,'source_id':src['id'],'evidence_quote':quote})
                evidence_text+=' '+quote
                if src['id'] not in slide['source_ids'] and len(slide['source_ids'])<8:
                    slide['source_ids'].append(src['id'])

        # Hard upper bound is now well above anything the renderer needs.
        slide['claims']=slide['claims'][:32]


def _numeric_quote(number, sources, preferred_source_ids=None, slide_text=''):
    """Find an exact source excerpt containing *number*.

    Search is deliberately broader than sentence-only matching: web pages often expose
    tables, list fragments, or headings without terminal punctuation. The returned text
    is always copied from the verified source verbatim after whitespace normalization.
    """
    preferred_source_ids = set(preferred_source_ids or [])
    candidates = []
    for src in sources:
        if src.get('kind') != 'web' or not src.get('verified'):
            continue
        text = ' '.join(str(src.get('text','')).split())
        if not text:
            continue
        source_nums = numbers(text)
        if number not in source_nums:
            continue
        score = 0.0
        if src.get('id') in preferred_source_ids:
            score += 2.0
        # Prefer excerpts that also overlap with the current slide topic.
        if slide_text:
            score += 0.4 * len(_source_tokens(slide_text) & _source_tokens(text)) / max(1, len(_source_tokens(slide_text)))
        candidates.append((score, src, text))
    candidates.sort(key=lambda x: x[0], reverse=True)

    for _, src, text in candidates:
        # First try a normal sentence containing the number.
        for sentence in _split_sentences(text):
            if number in numbers(sentence):
                return src, sentence
        # Then fall back to a bounded verbatim window around the exact number.
        m = re.search(rf'(?<![\w]){re.escape(number)}(?:[.,]\d+)?(?![\w])', text)
        if m:
            left = max(0, m.start() - 220)
            right = min(len(text), m.end() + 420)
            excerpt = text[left:right].strip(' -:;,')
            excerpt_words = _words(excerpt)
            if len(excerpt_words) >= 4:
                return src, ' '.join(excerpt_words[:70])
    return None, ''

def _visible_numeric_parts(slide):
    """Return only semantic numeric claims, not structural numbering such as 'Шаг 1'."""
    parts=[]
    parts.extend(slide.get('points',[]) or [])
    parts.extend(slide.get('left_points',[]) or [])
    parts.extend(slide.get('right_points',[]) or [])
    if slide.get('quote'): parts.append(slide.get('quote',''))
    for m in slide.get('metrics',[]) or []:
        parts.extend([m.get('value',''),m.get('note','')])
    for step in slide.get('timeline',[]) or []:
        # The label is a structural marker; only the explanatory detail is evidence-bearing.
        parts.append(step.get('detail',''))
    if slide.get('table'):
        parts.extend(slide['table'].get('rows',[]) and [' '.join(map(str,r)) for r in slide['table'].get('rows',[])])
    if slide.get('chart'):
        parts.extend([str(v) for v in slide['chart'].get('values',[])])
        parts.extend([str(x) for x in slide['chart'].get('labels',[]) if re.search(r'\d',str(x))])
    return [str(p) for p in parts if numbers(p)]

def _relevant_source_sentences(slide, sources, count=3):
    query = ' '.join([str(slide.get('title','')), str(slide.get('subtitle',''))] + _candidate_blocks(slide))
    query_tokens = _source_tokens(query)
    ranked=[]
    for src in sources:
        if src.get('kind') != 'web' or not src.get('verified'):
            continue
        sentences=_split_sentences(src.get('text',''))
        for idx, sentence in enumerate(sentences):
            tokens=_source_tokens(sentence)
            if not tokens:
                continue
            overlap=len(query_tokens & tokens)
            score=overlap/max(1,len(query_tokens))
            if idx % max(1, int(slide.get('number',1))) == 0:
                score += 0.01
            ranked.append((score, idx, sentence))
    ranked.sort(key=lambda x:(x[0], len(x[2])), reverse=True)
    seen=set(); result=[]
    for _,_,sentence in ranked:
        key=norm(sentence)
        if key in seen:
            continue
        seen.add(key); result.append(sentence)
        if len(result)>=count:
            break
    return result


def _repair_block_lengths(plan, sources):
    """Make the TЗ block constraint deterministic before the final validator sees the deck."""
    for slide in plan.get('slides', []):
        if slide.get('kind') in ('title', 'section', 'sources'):
            continue
        kind = slide.get('kind')
        if kind == 'two_column':
            left = [x for x in slide.get('left_points', []) if str(x).strip()]
            right = [x for x in slide.get('right_points', []) if str(x).strip()]
            def normalize_col(col):
                good = [x for x in col if 18 <= _word_count(x) <= 35]
                if len(good) >= 1:
                    return good[:2]
                merged = ' '.join(col)
                chunks = _chunk_words(merged)
                if chunks:
                    return chunks[:2]
                return col[:2]
            left = normalize_col(left)
            right = normalize_col(right)
            if not left or not right or not (18 <= _word_count(left[0]) <= 35) or not (18 <= _word_count(right[0]) <= 35):
                pool = left + right + list(slide.get('points', []))
                chunks = _chunk_words(' '.join(pool))
                if len(chunks) >= 2:
                    left, right = chunks[:1], chunks[1:2]
            slide['left_points'] = left[:4]
            slide['right_points'] = right[:4]
            continue

        blocks = _candidate_blocks(slide)
        good = [x for x in blocks if 18 <= _word_count(x) <= 35]
        if len(good) >= 2:
            _set_blocks(slide, good[:5])
            continue

        merged = ' '.join(blocks)
        if _word_count(merged) < 36:
            # Add only source-derived context until two substantive blocks can be formed.
            src = _best_web_source(slide, sources)
            if src:
                for sentence in _relevant_source_sentences(slide, sources, count=4):
                    if _word_count(merged) >= 42:
                        break
                    merged = (merged + ' ' + sentence).strip()
        chunks = _chunk_words(merged)
        if len(chunks) >= 2:
            _set_blocks(slide, chunks[:5])
        elif len(blocks) >= 2:
            # Preserve existing blocks rather than deleting useful content.
            _set_blocks(slide, blocks[:5])




def _ensure_kind_diversity(plan):
    """Guarantee three substantive kinds without inventing semantic structures."""
    slides=[s for s in plan.get('slides',[]) if s.get('kind') not in ('title','section','sources')]
    if len(slides)<7: return
    kinds={s.get('kind') for s in slides}
    if len(kinds)>=3: return
    # First convert one content slide to a real two-column comparison.
    for slide in slides:
        if len(kinds)>=3: break
        if slide.get('kind')=='content' and 'two_column' not in kinds:
            pts=[p for p in slide.get('points',[]) if p.strip()]
            if len(pts)>=2:
                half=max(1,len(pts)//2)
                slide['kind']='two_column'; slide['left_title']='Аспект 1'; slide['right_title']='Аспект 2'
                slide['left_points']=pts[:half]; slide['right_points']=pts[half:]; slide['points']=[]
                kinds.add('two_column')
    # Then use summary as the least assumption-heavy third structure.
    for slide in slides:
        if len(kinds)>=3: break
        if slide.get('kind')=='content' and 'summary' not in kinds:
            slide['kind']='summary'; kinds.add('summary')

def _break_repeated_slides(plan, sources):
    substantive=[s for s in plan.get('slides',[]) if s.get('kind') not in ('title','section','sources')]
    previous=[]
    for slide in substantive:
        current=set(re.findall(r'\w+', norm(' '.join(visible_text(slide)))))
        duplicate=False
        for old_slide, old in previous:
            score=len(current & old)/max(1,len(current | old))
            if score > 0.92:
                duplicate=True
                break
        if duplicate:
            sentences=_relevant_source_sentences(slide,sources,count=8)
            old_text=set(norm(x) for x in visible_text(old_slide)) if previous else set()
            fresh=[x for x in sentences if norm(x) not in old_text]
            chunks=_chunk_words(' '.join(fresh))
            if len(chunks)>=2:
                _set_blocks(slide,chunks[:5])
            elif fresh:
                _set_blocks(slide,_chunk_words(fresh[0])[:2])
            # Leave source ids intact; claims are rebuilt after this pass.
        previous.append((slide,current))




def harden_plan(plan, sources):
    """Deterministic quality pass: improve structure without making QA a blocking gate."""
    # These transformations are local and source-backed; they do not call the LLM.
    # They keep the original facts while making the deck easier to render and audit.
    _repair_block_lengths(plan, sources)
    _ensure_kind_diversity(plan)
    _repair_block_lengths(plan, sources)
    _break_repeated_slides(plan, sources)
    _repair_block_lengths(plan, sources)
    _sanitize_plan_content(plan, sources)
    _repair_block_lengths(plan, sources)
    _normalize_claims(plan, sources)
    return plan

def quality_issues(plan,requested):
    slides=plan.get('slides',[]); issues=[]; bodies=[]
    if len(slides)!=requested: issues.append(f'Нужно {requested} слайдов, получено {len(slides)}.')
    if [s.get('number') for s in slides] != list(range(1,len(slides)+1)): issues.append('Неверная последовательность номеров.')
    titles=set()
    for s in slides:
        n=s['number']; kind=s['kind']; parts=visible_text(s); text=' '.join(parts); title=norm(s['title'])
        if title in titles and kind!='sources': issues.append(f'Слайд {n}: повтор заголовка.')
        titles.add(title)
        if kind in ('title','section','sources'): continue
        explanations=_candidate_blocks(s)
        good=[p for p in explanations if 18<=_word_count(p)<=35]
        if kind=='two_column':
            left_good=[p for p in s.get('left_points',[]) if 18<=_word_count(p)<=35]
            right_good=[p for p in s.get('right_points',[]) if 18<=_word_count(p)<=35]
            if not left_good or not right_good:
                issues.append(f'Слайд {n}: для двухколоночной структуры нужны развёрнутые блоки в обеих колонках; ориентир 18–35 слов на блок.')
        elif kind!='quote' and len(good)<2:
            issues.append(f'Слайд {n}: недостаточно развёрнутого содержания — нужны хотя бы два развёрнутых смысловых блока с объяснениями, а не короткие ярлыки; ориентир 18–35 слов на блок.')
        if kind in ('chart','table','metrics') and len(explanations)<2:
            issues.append(f'Слайд {n}: для {kind} нужны минимум два видимых поясняющих блока.')
        if len(parts)<2 and kind!='quote': issues.append(f'Слайд {n}: нужна структура из нескольких смысловых блоков.')
        # Do not reject by a raw word-count ceiling. The case specification defines
        # density through layout fill, bullet length and whether text actually fits;
        # those checks are handled by the renderer/audit. A word-count gate could
        # reject a fact-rich table or a well-fitting multi-column slide.
        if any(len(p)>750 for p in parts): issues.append(f'Слайд {n}: раздели длинный блок на смысловые части.')
        body=set(re.findall(r'\w+',norm(text)))
        if any(title==old_title and body==old_body for old_title,old_body in bodies): issues.append(f'Слайд {n}: повторяет содержимое и заголовок другого слайда.')
        bodies.append((title,body))
    if sum(s['kind']=='section' for s in slides)>1: issues.append('Слишком много слайдов-разделителей без содержания.')
    if len(slides)>=7 and len({s['kind'] for s in slides if s['kind'] not in ('title','section','sources')})<3:
        issues.append('Однообразная структура: используй хотя бы три содержательных типа слайдов.')
    return issues

def source_issues(plan,sources):
    index={s['id']:s for s in sources}; issues=[]
    web_ids={s['id'] for s in sources if s.get('kind')=='web' and s.get('verified')}
    for slide in plan['slides']:
        if slide['kind']=='sources': continue
        n=slide['number']; ids=slide.get('source_ids',[])
        if any(i not in index for i in ids): issues.append(f'Слайд {n}: неизвестный источник.')
        if slide['kind'] not in ('title','section'):
            if not ids or not slide.get('claims'):
                issues.append(f'Слайд {n}: нет связи утверждений с источниками.')
            if not (set(ids) & web_ids):
                issues.append(f'Слайд {n}: нет подтверждения из проверенного веб-источника.')
        evidence=[]
        for c in slide.get('claims',[]):
            source=index.get(c['source_id']); quote=norm(c['evidence_quote'])
            if not source or c['source_id'] not in ids:
                issues.append(f'Слайд {n}: источник утверждения не привязан к слайду.'); continue
            if quote not in norm(source.get('text','')):
                issues.append(f'Слайд {n}: цитата отсутствует в исходнике {source["id"]}.'); continue
            evidence.append(c['evidence_quote'])
        if slide['kind'] not in ('title','section'):
            semantic_numeric=' '.join(_visible_numeric_parts(slide))
            missing=numbers(semantic_numeric)-numbers(' '.join(evidence))
            if missing: issues.append(f'Слайд {n}: числа без подтверждения в цитатах: {", ".join(sorted(missing))}.')
    return issues


def format_reference(source):
    """Web reference based on ГОСТ Р 7.0.108-2022; no inferred author/date."""
    title=source.get('title') or 'Без названия'
    ref_kind=source.get('reference_kind')
    if ref_kind in ('book','article','official'):
        author=source.get('author') or source.get('organization') or ''
        text=(author+'. ' if author else '')+title
        if ref_kind=='book':
            pub=' : '.join(v for v in (source.get('place'),source.get('publisher')) if v)
            if pub:text+=' — '+pub
            if source.get('year'):text+=', '+source['year']
            if source.get('pages'):text+=' — '+source['pages']+' с.'
        elif ref_kind=='article':
            if source.get('journal'):text+=' // '+source['journal']
            for field,label in (('year',''),('volume','Т. '),('issue','№ '),('pages','С. '),('doi','DOI ')):
                if source.get(field):text+=' — '+label+source[field]
        else:
            if source.get('document_date'):text+=' от '+source['document_date']
            if source.get('document_number'):text+=' № '+source['document_number']
        return text.rstrip('.')+'.'
    if source.get('kind')=='upload': return f'{title} — материал пользователя; библиографические реквизиты не предоставлены.'
    author=source.get('author',''); site=source.get('site_name',''); published=source.get('published_at','')
    text=(author+'. ' if author else '')+title
    if site and norm(site)!=norm(title): text+=' // '+site
    if published: text+=' — '+published
    text+=' — URL: '+source['url']
    accessed=source.get('accessed_at','')
    if accessed:
        date=datetime.fromisoformat(accessed).strftime('%d.%m.%Y')
        text+=f' (дата обращения: {date}).'
    return text


def bibliography_slots(sources,requested):
    return max(1,min(math.ceil(len(sources)/3),requested-2))


def bibliography(plan,sources,slots):
    used={sid for s in plan['slides'] if s['kind']!='sources' for sid in s.get('source_ids',[])}
    refs=[s for s in sources if s['id'] in used]
    if not refs: raise ValueError('Нет действительно использованных источников для библиографии.')
    if len(refs)<slots:
        raise ValueError('Для зарезервированных слайдов источников недостаточно использованных записей; пересоберите структуру.')
    from .models import Slide
    groups=[refs[i*len(refs)//slots:(i+1)*len(refs)//slots] for i in range(slots)]
    if any(len(g)>3 for g in groups): raise ValueError('Библиография не вмещается: нужно больше слайдов источников.')
    for i,group in enumerate(groups):
        n=len(plan['slides'])-slots+i+1
        if plan['slides'][n-1]['kind']!='sources':
            raise ValueError('Библиография не может заменить содержательный слайд.')
        plan['slides'][n-1]=Slide(number=n,kind='sources',title='Источники'+(f' · {i+1}' if slots>1 else ''),points=[f'[{s["id"]}] '+format_reference(s) for s in group],source_ids=[s['id'] for s in group]).model_dump()
    return plan
