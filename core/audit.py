from __future__ import annotations

import math
import re
from pathlib import Path
from pptx import Presentation
from .renderer import all_shapes, _fits, EMU
from .models import visible_text
from .quality import norm


def _rect(shape):
    return float(shape.left), float(shape.top), float(shape.left + shape.width), float(shape.top + shape.height)


def _intersection_area(a, b):
    left=max(a[0],b[0]); top=max(a[1],b[1]); right=min(a[2],b[2]); bottom=min(a[3],b[3])
    return max(0.0,right-left)*max(0.0,bottom-top)


def _area(r):
    return max(0.0,r[2]-r[0])*max(0.0,r[3]-r[1])


def _shape_kind(shape):
    return str(getattr(shape, 'name', '')).split(':',1)[-1] if ':' in str(getattr(shape,'name','')) else str(getattr(shape,'shape_type','unknown'))


def _safe_rgb_from_font(run):
    try:
        if run.font.color and run.font.color.type is not None and run.font.color.rgb:
            return str(run.font.color.rgb).upper()
    except Exception:
        return None
    return None


def _contrast_ratio(hex1, hex2):
    def lum(h):
        vals=[int(h[i:i+2],16)/255 for i in (0,2,4)]
        vals=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in vals]
        return 0.2126*vals[0]+0.7152*vals[1]+0.0722*vals[2]
    try:
        a=lum(hex1); b=lum(hex2)
        return (max(a,b)+0.05)/(min(a,b)+0.05)
    except Exception:
        return None


def _shape_text(shape):
    try:
        if shape.has_text_frame:
            return shape.text or ''
    except Exception:
        pass
    return ''


def _bullet_count(shape):
    try:
        if not shape.has_text_frame: return 0
        count=0
        for p in shape.text_frame.paragraphs:
            if not (p.text or '').strip():
                continue
            has_bullet=False
            try:
                ppr=p._p.pPr
                has_bullet = ppr is not None and (getattr(ppr, 'buChar', None) is not None or getattr(ppr, 'buAutoNum', None) is not None)
            except Exception:
                pass
            if not has_bullet and re.match(r'^(?:[-–—•◦▪]|\d+[.)])\s+', (p.text or '').strip()):
                has_bullet=True
            if has_bullet:
                count += 1
        return count
    except Exception:
        return 0

def _background_color(slide, slide_w, slide_h):
    # Prefer an explicit slide background; otherwise inspect the largest non-generated
    # full/near-full background rectangle. Fall back to white only when no signal exists.
    try:
        fill=slide.background.fill
        if fill.type is not None and fill.fore_color.type is not None and fill.fore_color.rgb:
            return str(fill.fore_color.rgb).upper()
    except Exception:
        pass
    best=None;best_area=0
    for shape in all_shapes(slide.shapes):
        if str(getattr(shape,'name','')).startswith('generated:'):
            continue
        try:
            if not shape.fill or shape.fill.type is None or shape.fill.fore_color.type is None or not shape.fill.fore_color.rgb:
                continue
            area=_area(_rect(shape))
            if area>best_area and area >= 0.65*slide_w*slide_h:
                best_area=area;best=str(shape.fill.fore_color.rgb).upper()
        except Exception:
            continue
    return best or 'FFFFFF'


def _slide_fill_ratio(slide, slide_w, slide_h):
    slide_area=slide_w*slide_h
    if not slide_area: return 0.0
    # Approximate visual occupancy. Background/master objects are ignored.
    union=[]
    for shape in all_shapes(slide.shapes):
        if not str(getattr(shape,'name','')).startswith('generated:'):
            continue
        r=_rect(shape)
        area=_area(r)
        if area<=0: continue
        union.append(r)
    if not union: return 0.0
    # Exact union is unnecessary for QA: use sampled 20x12 grid for stable occupancy.
    cols,rows=20,12; hit=0
    for ry in range(rows):
        y1=ry/rows*slide_h; y2=(ry+1)/rows*slide_h
        cy=(y1+y2)/2
        for rx in range(cols):
            x1=rx/cols*slide_w; x2=(rx+1)/cols*slide_w
            cx=(x1+x2)/2
            if any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in union): hit+=1
    return hit/(rows*cols)


def audit_deck(path, plan=None, template_spec=None):
    prs=Presentation(str(path));issues=[]
    stats={
        'slides':len(prs.slides),'empty_slides':0,'text_chars':0,'shapes':0,
        'generated_shapes':0,'overlaps':0,'fonts':{},'colors':{},'tables':0,'charts':0,
        'density_ratios':[],
    }
    if plan and len(prs.slides)!=len(plan['slides']):
        issues.append({'slide':0,'severity':'critical','kind':'slide_loss','message':'Число слайдов изменилось при экспорте.','fix':'Повторить верстку и проверить экспорт.'})

    allowed_fonts={str(x[0]) for x in ((template_spec or {}).get('design_tokens',{}).get('fonts',[]) or [])}
    template_colors={str(x[0]).upper() for x in ((template_spec or {}).get('design_tokens',{}).get('colors',[]) or [])}
    fill_map={'FFFFFF','FAFBFD','F6F7F9','000000','0B0C10'}
    for i,slide in enumerate(prs.slides,1):
        texts=[]; generated=[]; slide_bg=_background_color(slide,prs.slide_width,prs.slide_height)
        for shape in all_shapes(slide.shapes):
            stats['shapes']+=1
            name=str(getattr(shape,'name',''))
            if name.startswith('generated:'):
                stats['generated_shapes']+=1; generated.append(shape)
            if shape.has_text_frame:
                texts.append(shape.text)
                # bounds for every generated object, not only text
                if name.startswith('generated:'):
                    if shape.left<0 or shape.top<0 or shape.left+shape.width>prs.slide_width or shape.top+shape.height>prs.slide_height:
                        issues.append({'slide':i,'severity':'critical','kind':'bounds','message':'Объект вышел за границы слайда.','fix':'Уменьшить/переместить объект внутрь макета.'})
                    sizes=[r.font.size.pt for p in shape.text_frame.paragraphs for r in p.runs if r.font.size]
                    if sizes and not _fits(shape.text,shape.width/EMU,shape.height/EMU,max(sizes)):
                        issues.append({'slide':i,'severity':'major','kind':'overflow','message':'Текст может не помещаться в рамку.','fix':'Сократить текст или увеличить допустимую область.'})
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if run.font.name:
                            stats['fonts'][run.font.name]=stats['fonts'].get(run.font.name,0)+1
                            if allowed_fonts and name.startswith('generated:') and run.font.name not in allowed_fonts:
                                issues.append({'slide':i,'severity':'minor','kind':'font','message':f'Шрифт «{run.font.name}» не найден в токенах выбранного шаблона.','fix':'Использовать гарнитуру из дизайн-системы шаблона.'})
                        rgb=_safe_rgb_from_font(run)
                        if rgb:
                            stats['colors'][rgb]=stats['colors'].get(rgb,0)+1
                            if template_colors and name.startswith('generated:') and rgb not in template_colors:
                                issues.append({'slide':i,'severity':'minor','kind':'color','message':f'Цвет текста #{rgb} не найден в палитре шаблона.','fix':'Использовать цвет из палитры шаблона или добавить токен.'})
                            ratio=_contrast_ratio(rgb, slide_bg)
                            if ratio is not None and ratio<4.5 and name.startswith('generated:'):
                                issues.append({'slide':i,'severity':'major','kind':'contrast','message':f'Контраст текста около {ratio:.1f}:1, ниже ориентира 4.5:1.','fix':'Изменить цвет текста или фон.'})
            if shape.has_table:
                stats['tables']+=1
                rows=len(shape.table.rows); cols=len(shape.table.columns)
                texts.extend(c.text for row in shape.table.rows for c in row.cells)
                if name.startswith('generated:') and (rows>7 or cols>5):
                    issues.append({'slide':i,'severity':'minor','kind':'table_density','message':f'Таблица содержит {rows} строк и {cols} столбцов. Ориентир ТЗ — не более 7 × 5.','fix':'Сократить таблицу или разделить её на два слайда.'})
            if shape.has_chart:
                stats['charts']+=1
                try:
                    texts.extend(c.label for c in shape.chart.plots[0].categories)
                    for series in shape.chart.series:
                        texts.append(series.name); texts.extend(format(v,'.12g') for v in series.values)
                    series_count=len(shape.chart.series)
                    if name.startswith('generated:') and series_count>5:
                        issues.append({'slide':i,'severity':'minor','kind':'chart_density','message':f'Диаграмма содержит {series_count} серий; ориентир ТЗ — не более 5.','fix':'Сократить число серий.'})
                except Exception:
                    pass
        # Overlap check only on generated objects; background/master shapes are excluded.
        for a_idx,a in enumerate(generated):
            ra=_rect(a); aa=_area(ra)
            if aa<=0: continue
            for b in generated[a_idx+1:]:
                rb=_rect(b); ab=_area(rb); inter=_intersection_area(ra,rb)
                if inter<=0: continue
                ratio=inter/max(1.0,min(aa,ab))
                # Small text/image edge contacts can be intentional; report substantive overlap.
                area_ratio=min(aa,ab)/max(aa,ab)
                # Ignore a small label fully sitting inside a larger narrative area;
                # this can be a deliberate section/annotation pattern. Real collisions
                # remain visible when objects have comparable area or partial overlap.
                tiny_contained = ratio>=0.9 and area_ratio<0.22
                if ratio>=0.12 and not tiny_contained and not (a.has_table and b.has_text_frame) and not (b.has_table and a.has_text_frame):
                    issues.append({'slide':i,'severity':'major','kind':'overlap','message':f'Два сгенерированных объекта перекрываются примерно на {ratio:.0%}.','fix':'Разнести блоки или изменить размеры.'})
                    stats['overlaps']+=1
        text=' '.join(texts);stats['text_chars']+=len(text)
        if not text.strip():
            stats['empty_slides']+=1;issues.append({'slide':i,'severity':'critical','kind':'empty','message':'Пустой слайд.','fix':'Добавить содержание или удалить слайд.'})
        if 'lorem ipsum' in text.lower() or re.search(r'(^|\W)(XXX|TODO)(\W|$)',text,re.I) or 'вставьте текст' in text.lower():
            issues.append({'slide':i,'severity':'major','kind':'placeholder_text','message':'На слайде остался служебный текст-заглушка.','fix':'Заменить заглушку содержанием.'})
        if plan and i<=len(plan['slides']):
            expected=[plan['slides'][i-1]['title']]+visible_text(plan['slides'][i-1])
            normalized_text=norm(text)
            for fragment in expected:
                frag_norm=norm(fragment)
                if not frag_norm: continue
                # Exact comparison for short labels/titles. Long prose can be legitimately
                # reflowed or shortened by the renderer; require its opening semantic window.
                probe=frag_norm if len(frag_norm)<=180 else frag_norm[:90]
                if probe not in normalized_text:
                    severity='critical' if len(frag_norm)<=180 else 'major'
                    issues.append({'slide':i,'severity':severity,'kind':'content_loss','message':'При вёрстке потерян блок: '+fragment[:100],'fix':'Вернуть потерянный контент из плана.'})
        # Bullet and occupancy density checks are advisory and use the actual rendered objects.
        bullets=sum(_bullet_count(s) for s in generated if getattr(s,'has_text_frame',False))
        if bullets>6:
            issues.append({'slide':i,'severity':'minor','kind':'bullet_density','message':f'На слайде около {bullets} текстовых пунктов; ориентир ТЗ — не более 6.','fix':'Объединить или сократить пункты.'})
        ratio=_slide_fill_ratio(slide,prs.slide_width,prs.slide_height);stats['density_ratios'].append(round(ratio,3))
        if ratio<0.25:
            issues.append({'slide':i,'severity':'minor','kind':'underfilled','message':f'Сгенерированная область занимает около {ratio:.0%} слайда; ориентир ТЗ — не менее четверти.','fix':'Добавить объяснение/визуализацию или упростить композицию с намеренным обоснованием.'})
        elif ratio>0.75:
            issues.append({'slide':i,'severity':'minor','kind':'overfilled','message':f'Сгенерированная область занимает около {ratio:.0%} слайда; ориентир ТЗ — не более трёх четвертей.','fix':'Сократить или переразместить элементы.'})
    # Exact duplicate visible slides.
    seen_slides={}
    for i,slide in enumerate(prs.slides,1):
        key=' '.join(_shape_text(s).strip() for s in all_shapes(slide.shapes) if _shape_text(s).strip())
        key=norm(key)
        if key and key in seen_slides:
            issues.append({'slide':i,'severity':'major','kind':'duplicate','message':f'Слайд визуально/текстово дублирует слайд {seen_slides[key]}.','fix':'Изменить содержание или удалить дубликат.'})
        elif key: seen_slides[key]=i

    unique=[]; seen=set()
    for issue in issues:
        k=(issue.get('slide'),issue.get('kind'),issue.get('message'))
        if k in seen: continue
        seen.add(k);unique.append(issue)
    # Score is a diagnostic signal, never the sole pass/fail criterion.
    weights={'critical':18,'major':9,'minor':3}
    score=max(0,100-sum(weights.get(x.get('severity','minor'),3) for x in unique))
    return {
        'score':score,'issues':unique,'stats':stats,
        'scope':'Детерминированная проверка геометрии, плотности, типографики, палитры, контраста, таблиц/диаграмм, заглушек, дубликатов и сохранности видимого контента. Семантическая оценка выполняется отдельными LLM-проверками.',
        'severity_model':'critical=блокирующая структурная ошибка; major=существенное замечание; minor=ориентир плотности/дизайн-системы.',
    }
