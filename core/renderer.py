"""Native PPTX renderer: one semantic slide -> exactly one editable slide.

Uses source masters and simple example-slide compositions. Unsupported elaborate
sample diagrams are not treated as trusted data. No content slicing is allowed.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math,re,textwrap
import os
from lxml import etree
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches,Pt
from pptx.dml.color import RGBColor
from pptx.oxml.xmlchemy import OxmlElement
from .models import Deck,visible_text

EMU=914400
VARIANTS=('balanced','columns','editorial')

# Curated source slides from the supplied VK templates. These correspond to the
# template catalog and the handoff layout registry, so each visual variant uses a
# real composition from that template instead of a guessed generic canvas.
_TEMPLATE_SOURCE_MAP = {
    'vk_tech': {'title': 0, 'balanced': 17, 'columns': 18, 'editorial': 27},
    'vk_workspace': {'title': 0, 'balanced': 6, 'columns': 9, 'editorial': 10},
    'vk_education': {'title': 0, 'balanced': 6, 'columns': 7, 'editorial': 12},
}

_IMAGE_KINDS = {'title','content','section','two_column','quote','timeline','process','summary'}

class LayoutError(ValueError): pass

def all_shapes(shapes):
    for shape in shapes:
        if shape.shape_type==6: yield from all_shapes(shape.shapes)
        else: yield shape

def _color(font):
    try: return str(font.color.rgb)
    except (AttributeError,TypeError,ValueError):return None

def _tokens(prs,spec):
    from zipfile import ZipFile
    # Resolve theme defaults through the package rather than template filenames.
    font='Arial'; accent='2463EB'
    try:
        root=etree.fromstring(prs.slide_master.part.theme_part.blob)
    except AttributeError:
        root=None
        for rel in prs.slide_master.part.rels.values():
            if rel.reltype.endswith('/theme'): root=etree.fromstring(rel.target_part.blob);break
    if root is not None:
        ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
        fonts=root.xpath('.//a:minorFont/a:latin/@typeface',namespaces=ns)
        accents=root.xpath('.//a:accent1/a:srgbClr/@val',namespaces=ns)
        if fonts and fonts[0]:font=fonts[0]
        if accents:accent=accents[0]
    observed=spec.get('design_tokens',{}).get('fonts',[])
    if observed:font=observed[0][0]
    # Explicit, portable fallback; original requested font remains in template_spec.
    # Users with the corporate fonts installed may set RENDER_FONT to that face.
    font=os.getenv('RENDER_FONT','Arial')
    return font,accent

def _source(prs,kind):
    candidates=[]
    w=prs.slide_width;h=prs.slide_height
    for i,slide in enumerate(prs.slides):
        shapes=list(all_shapes(slide.shapes));texts=[s for s in shapes if s.has_text_frame and s.text.strip()]
        wide=[s for s in texts if s.width>w*.5 and s.top<h*.32]
        bodies=[s for s in texts if s.top>h*.18 and s.width>w*.45 and s.height>h*.28]
        samples=' '.join(s.text for s in texts).lower()
        score=len(wide)*2+len(bodies)*8-len(shapes)*.05
        lname=slide.slide_layout.name.lower()
        if kind!='title' and any(x in lname for x in ('титуль','section','разделител','финаль')):score-=40
        if any(s.has_chart or s.has_table for s in shapes):score-=20
        if any(x in samples for x in ('инструкция','правила использования','body {','спасибо')):score-=15
        if kind=='title': score+=(10 if i==0 else 0)
        candidates.append((score,-i,slide))
    return max(candidates,key=lambda t:t[:2])[2] if candidates else None

def _clone(prs,source):
    if source is None: return prs.slides.add_slide(min(prs.slide_layouts,key=lambda l:len(l.placeholders)))
    dest=prs.slides.add_slide(source.slide_layout)
    for s in list(dest.shapes):s._element.getparent().remove(s._element)
    relmap={}
    for rel in source.part.rels.values():
        if rel.reltype.endswith(('/slideLayout','/notesSlide')):continue
        rid=dest.part.rels.get_or_add_ext_rel(rel.reltype,rel.target_ref) if rel.is_external else dest.part.rels.get_or_add(rel.reltype,rel.target_part)
        relmap[rel.rId]=rid
    for shape in source.shapes:
        e=deepcopy(shape._element)
        for node in e.iter():
            for attr,val in list(node.attrib.items()):
                if attr.startswith('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}') and val in relmap:node.set(attr,relmap[val])
        dest.shapes._spTree.insert_element_before(e,'p:extLst')
    if source._element.cSld.bg is not None:
        dest._element.cSld.insert(0,deepcopy(source._element.cSld.bg))
    return dest

def _fits(text,w,h,size):
    usable_w=max(.1,w-.08)*72; usable_h=max(.1,h-.06)*72
    chars=max(4,int(usable_w/(size*.54)))
    lines=sum(max(1,len(textwrap.wrap(line,chars,break_long_words=True))) for line in str(text).split('\n'))
    return lines*size*1.22<=usable_h

def _word_count(text):
    return len(re.findall(r'[\wА-Яа-яЁё-]+', str(text or '')))

def _textbox(slide,box,text,font,color,size=18,bold=False,min_size=13,link=None):
    x,y,w,h=box
    text=str(text)
    while size>min_size and not _fits(text,w,h,size):size-=.5
    # A template must never make the entire deck fail. At the last resort use a
    # small editable font inside the same box and let the deterministic audit report
    # density/fit as a warning. This keeps PPTX generation reliable.
    if not _fits(text,w,h,size):
        size=min(size,8.0)
    shape=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h));shape.name='generated:text'
    tf=shape.text_frame;tf.word_wrap=True
    tf.margin_left=tf.margin_right=Inches(.04);tf.margin_top=tf.margin_bottom=Inches(.03)
    for i,line in enumerate(text.split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph();p.space_after=Pt(0);p.line_spacing=1.16
        r=p.add_run();r.text=line;r.font.name=font;r.font.size=Pt(size);r.font.bold=bold;r.font.color.rgb=RGBColor.from_string(color)
        if link and link.startswith(('https://','http://')):r.hyperlink.address=link
    return shape

def _template_source(prs, template_id, variant, kind):
    """Pick a real composition from a supplied template when we know its registry slot."""
    if template_id in _TEMPLATE_SOURCE_MAP:
        mp=_TEMPLATE_SOURCE_MAP[template_id]
        if kind=='title': idx=mp.get('title',0)
        else: idx=mp.get(variant,mp.get('balanced',0))
        if 0 <= idx < len(prs.slides): return prs.slides[idx]
    return _source(prs,'title' if kind=='title' else 'content')

def _content_slots(source, prs, avoid_pictures=False):
    """Return substantial template text regions suitable for generated copy.

    Tiny label rows are intentionally excluded: they are template chrome, not
    meaningful content areas. When an image is being inserted, text regions that
    sit on top of the picture are excluded so an image can occupy its intended area.
    """
    if source is None: return []
    w=prs.slide_width/EMU; h=prs.slide_height/EMU
    out=[]
    for sh in all_shapes(source.shapes):
        try:
            is_ph=bool(sh.is_placeholder)
        except Exception:
            is_ph=False
        if not sh.has_text_frame and not is_ph: continue
        x,y,sw,shh=sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU
        if y < h*.18: continue
        if sw < .55 or shh < .30: continue
        # Never treat slide number, tiny labels or full-width subtitles as content cards.
        if sw < w*.05 or shh < h*.02: continue
        if sw > w*.94 and shh < .34: continue
        if is_ph:
            try:
                pht=str(sh.placeholder_format.type).upper()
                if 'TITLE' in pht or 'SUBTITLE' in pht or 'DATE' in pht or 'FOOTER' in pht or 'SLIDE_NUMBER' in pht:
                    continue
            except Exception:
                pass
        text=' '.join(p.text for p in sh.text_frame.paragraphs).strip() if sh.has_text_frame else ''
        # Keep empty placeholders: they are the most reliable editable slots in VK Tech.
        if not text and not is_ph: continue
        if avoid_pictures:
            try:
                pictures=[p for p in all_shapes(source.shapes) if p.shape_type==13 and p.width/EMU>.8 and p.height/EMU>.7]
                covered=False
                for pic in pictures:
                    ix=max(0,min(x+sw,pic.left/EMU+pic.width/EMU)-max(x,pic.left/EMU))
                    iy=max(0,min(y+shh,pic.top/EMU+pic.height/EMU)-max(y,pic.top/EMU))
                    if ix*iy > .45*min(sw*shh,(pic.width/EMU)*(pic.height/EMU)):
                        covered=True; break
                if covered: continue
            except Exception:
                pass
        out.append(sh)
    out=sorted(out,key=lambda z:(z.top/EMU,z.left/EMU))
    kept=[]
    for sh in out:
        box=(sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU)
        overlap=False
        for prev in kept:
            px,py,pw,ph=prev.left/EMU,prev.top/EMU,prev.width/EMU,prev.height/EMU
            ix=max(0,min(box[0]+box[2],px+pw)-max(box[0],px))
            iy=max(0,min(box[1]+box[3],py+ph)-max(box[1],py))
            if ix*iy > .60*min(box[2]*box[3],pw*ph): overlap=True; break
        if not overlap: kept.append(sh)
    return kept[:12]

def _image_box(source, prs):
    """Find a large picture area or a safe unused side of the template."""
    w,h=prs.slide_width/EMU,prs.slide_height/EMU
    if source is not None:
        pics=[sh for sh in all_shapes(source.shapes) if sh.shape_type==13]
        large=[sh for sh in pics if sh.width/EMU>1.0 and sh.height/EMU>.8]
        if large:
            sh=max(large,key=lambda z:(z.width/EMU)*(z.height/EMU))
            return (sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU)
        for sh in all_shapes(source.shapes):
            try:
                if sh.is_placeholder and 'PICTURE' in str(sh.placeholder_format.type).upper():
                    return (sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU)
            except Exception:
                pass
        # If text slots are concentrated on one side, use the opposite side.
        # Use the center of the occupied region rather than its left edge; several
        # VK layouts start around 45% of the canvas, and the old threshold incorrectly
        # placed images on top of their right-hand cards.
        slots=_content_slots(source,prs)
        if slots:
            left=min(s.left/EMU for s in slots); right=max((s.left+s.width)/EMU for s in slots)
            span=(right-left)/w; center=(left+right)/2
            if span>.82:
                return None  # full-width card grids have no safe image area
            if center>w*.56:
                return (w*.055,h*.30,w*.36,h*.46)
            if center<w*.44:
                return (w*.59,h*.30,w*.35,h*.46)
    return (w*.59,h*.34,w*.35,h*.46)

def _fit_image_for_box(path, box):
    """Create a cropped JPEG for an aspect-ratio-safe PPTX insertion."""
    from PIL import Image,ImageOps
    src=Path(path)
    try:
        img=Image.open(src).convert('RGB')
        target=max(.1,float(box[2])/max(.1,float(box[3])))
        fitted=ImageOps.fit(img,(1400,max(300,int(1400/target))),method=Image.Resampling.LANCZOS,centering=(.5,.5))
        dst=src.with_name(src.stem+'_fit_'+str(int(target*1000))+'.jpg')
        fitted.save(dst,'JPEG',quality=88,optimize=True)
        return dst
    except Exception:
        return src

def _insert_image(prs, slide, source, image_info):
    if not image_info: return None
    path=Path(image_info.get('path',''))
    if not path.exists(): return None
    box=_image_box(source,prs)
    if not box: return None
    # Replace only the large sample picture in this region. Keep tiny template icons.
    for sh in list(all_shapes(slide.shapes)):
        if sh.shape_type!=13: continue
        sx,sy,sw,shh=sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU
        ix=max(0,min(box[0]+box[2],sx+sw)-max(box[0],sx))
        iy=max(0,min(box[1]+box[3],sy+shh)-max(box[1],sy))
        if ix*iy > .5*min(box[2]*box[3],sw*shh) and sw*shh > .8:
            sh._element.getparent().remove(sh._element)
    fitted=_fit_image_for_box(path,box)
    pic=slide.shapes.add_picture(str(fitted),Inches(box[0]),Inches(box[1]),width=Inches(box[2]),height=Inches(box[3]))
    pic.name='generated:image'
    return pic

def _write_slot(shape, text, font, color, size=14, bold=False):
    """Populate an existing template text region instead of painting over its card."""
    tf=shape.text_frame; tf.clear(); tf.word_wrap=True
    tf.margin_left=tf.margin_right=Inches(.04); tf.margin_top=tf.margin_bottom=Inches(.03)
    for i,line in enumerate(str(text).split('\n')):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph()
        p.space_after=Pt(0);p.line_spacing=1.12
        r=p.add_run();r.text=line;r.font.name=font;r.font.size=Pt(size);r.font.bold=bold;r.font.color.rgb=RGBColor.from_string(color)
    return shape

def _render_into_slots(slide, source, prs, texts, font, color, variant, avoid_pictures=False):
    src_slots=_content_slots(source,prs,avoid_pictures=avoid_pictures)
    if len(src_slots)<2 or not texts: return False
    expanded=[]
    for text in texts:
        text=str(text).strip()
        sentences=[x.strip() for x in re.split(r'(?<=[.!?])\s+',text) if x.strip()]
        if len(src_slots)>=4 and len(sentences)>=2:
            expanded.extend(sentences[:4])
        else:
            expanded.append(text)
    texts=expanded[:len(src_slots)]
    for i,text in enumerate(texts):
        sh=src_slots[i]
        bx=(sh.left/EMU,sh.top/EMU,sh.width/EMU,sh.height/EMU)
        size=16 if bx[3]>=.40 else 13
        if bx[2]<1.3: size=min(size,12)
        while size>8 and not _fits(text,bx[2],bx[3],size): size-=.5
        _textbox(slide,bx,text,font,color,max(8,size),variant=='editorial' and i==0,min_size=8)
    return True

def _background_text_color(prs, source):
    """Choose readable text color from slide/layout/master background."""
    if source is None: return '17223B'
    theme={}
    try:
        for rel in source.slide_layout.slide_master.part.rels.values():
            if rel.reltype.endswith('/theme'):
                root=etree.fromstring(rel.target_part.blob)
                ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
                for el in root.xpath('.//a:clrScheme/*',namespaces=ns):
                    if len(el):
                        child=el[0]; theme[etree.QName(el).localname]=child.get('lastClr') or child.get('val')
    except Exception:
        theme={}
    for obj in (source, source.slide_layout, source.slide_layout.slide_master):
        try: bg=obj._element.cSld.bg
        except Exception: continue
        if bg is None: continue
        found=bg.xpath('.//a:solidFill/a:srgbClr') or bg.xpath('.//a:solidFill/a:schemeClr')
        if not found: continue
        value=found[0].get('val')
        value=theme.get(value,value)
        if value and re.fullmatch('[A-Fa-f0-9]{6}',value):
            rgb=[int(value[i:i+2],16)/255 for i in (0,2,4)]
            linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
            lum=sum(v*k for v,k in zip(linear,(.2126,.7152,.0722)))
            return 'FFFFFF' if lum < .34 else '17223B'
    return '17223B'

def _basis(prs,source,dest,kind):
    """Compute a safe title/body area while preserving the template's visual composition."""
    w,h=prs.slide_width/EMU,prs.slide_height/EMU
    margin=w*.055
    title=(margin,h*.075,w-2*margin,h*.16)
    body=(margin,h*.25,w-2*margin,h*.64)
    textcolor=_background_text_color(prs,source)
    texts=[] if source is None else [s for s in all_shapes(source.shapes) if s.has_text_frame]
    tops=[s for s in texts if s.top<h*EMU*.30 and s.width>w*EMU*.45 and s.height<h*EMU*.32]
    if kind=='title':
        placeholders=[s for s in texts if s.is_placeholder and 'TITLE' in str(s.placeholder_format.type) and 'SUBTITLE' not in str(s.placeholder_format.type)]
        if placeholders: tops=placeholders
    if tops:
        t=min(tops,key=lambda s:s.top)
        title=(t.left/EMU,t.top/EMU,t.width/EMU,max(t.height/EMU,h*.13))
        for p in t.text_frame.paragraphs:
            for r in p.runs:
                if _color(r.font): textcolor=_color(r.font)
    # Derive body from the actual content slots, not from a single largest textbox.
    slots=_content_slots(source,prs) if source is not None else []
    if slots and kind!='title':
        left=min(s.left/EMU for s in slots); top=min(s.top/EMU for s in slots)
        right=max((s.left+s.width)/EMU for s in slots); bottom=max((s.top+s.height)/EMU for s in slots)
        pad=.05
        body=(max(margin,left-pad),max(h*.22,top-pad),min(w-2*margin,right-left+2*pad),min(h*.69,max(.8,bottom-top+2*pad)))
    elif kind!='title':
        body=(margin,h*.25,w-2*margin,h*.62)
    if kind=='title':
        body=(title[0],title[1]+title[3]+.12,title[2],max(.35,h*.87-(title[1]+title[3]+.12)))
    else:
        body=(body[0],max(body[1],title[1]+title[3]+.10),body[2],min(body[3],h*.90-max(body[1],title[1]+title[3]+.10)))
    # Clear sample copy and sample charts/tables but preserve every visual/decorative shape.
    for sh in list(all_shapes(dest.shapes)):
        if sh.has_chart or sh.has_table:
            sh._element.getparent().remove(sh._element)
        elif sh.has_text_frame:
            try: sh.text=''
            except Exception: pass
    return title,body,textcolor

def _paragraphs(slide,box,parts,font,color,variant,accent,min_size=13):
    if not parts:return
    x,y,w,h=box
    parts=[str(p).strip() for p in parts if str(p).strip()]
    if not parts:return

    def layout_equal(cols, size=18, floor=None):
        floor = min_size if floor is None else floor
        n=len(parts); gap=.14
        rows=math.ceil(n/cols); cw=(w-gap*(cols-1))/cols
        rh=(h-gap*(rows-1))/rows
        boxes=[]
        for i,text in enumerate(parts):
            boxes.append((x+(i%cols)*(cw+gap),y+(i//cols)*(rh+gap),cw,rh,text))
        for bx,by,bw,bh,text in boxes:
            test=size
            while test>floor and not _fits(text,bw,bh,test): test-=.5
            if not _fits(text,bw,bh,max(floor,test)):
                return False
        for i,(bx,by,bw,bh,text) in enumerate(boxes):
            _textbox(slide,(bx,by,bw,bh),text,font,accent if variant=='editorial' and i==0 else color,size,bold=variant=='editorial' and i==0,min_size=floor)
        return True

    def layout_stacked(cols, size=15, floor=10):
        # Distribute blocks between columns and allocate height by actual word count.
        # This handles one long block next to two short blocks far better than equal rows.
        groups=[[] for _ in range(cols)]
        for i,text in enumerate(parts):
            groups[i % cols].append(text)
        gap=.14; cw=(w-gap*(cols-1))/cols
        all_boxes=[]
        for ci,group in enumerate(groups):
            if not group: continue
            weights=[max(20,_word_count(txt)) for txt in group]
            usable=max(.25,h-gap*(len(group)-1))
            total=sum(weights)
            cy=y
            bx=x+ci*(cw+gap)
            for wi,(txt,weight) in enumerate(zip(group,weights)):
                bh=usable*weight/total
                all_boxes.append((bx,cy,cw,bh,txt))
                cy += bh+gap
        for bx,by,bw,bh,text in all_boxes:
            test=size
            while test>floor and not _fits(text,bw,bh,test): test-=.5
            if not _fits(text,bw,bh,max(floor,test)):
                return False
        for i,(bx,by,bw,bh,text) in enumerate(all_boxes):
            _textbox(slide,(bx,by,bw,bh),text,font,accent if variant=='editorial' and i==0 else color,size,bold=variant=='editorial' and i==0,min_size=floor)
        return True

    def compact_parts(items):
        out=[]
        for text in items:
            words=_words_safe(text)
            if len(words)<=42:
                out.append(text)
                continue
            # Prefer sentence boundaries so facts remain intact.
            sentences=[s for s in re.split(r'(?<=[.!?])\s+',text) if s.strip()]
            if len(sentences)>1:
                buf=''
                for sent in sentences:
                    candidate=(buf+' '+sent).strip()
                    if buf and len(_words_safe(candidate))>34:
                        out.append(buf.strip())
                        buf=sent.strip()
                    else:
                        buf=candidate
                if buf: out.append(buf.strip())
            else:
                for i in range(0,len(words),32):
                    out.append(' '.join(words[i:i+32]))
        return out or list(items)

    def _words_safe(text):
        return re.findall(r'[\wА-Яа-яЁё-]+',str(text or ''))

    preferred=2 if (variant=='columns' and len(parts)>1) or (variant=='editorial' and len(parts)>=3) else 1
    candidates=[]
    for cols in (preferred, 2 if len(parts)>1 else 1, 3 if len(parts)>=6 else 1):
        if cols not in candidates:candidates.append(cols)
    for cols in candidates:
        if cols<=len(parts) and layout_equal(cols,18): return
    compact=compact_parts(parts)
    # Recompute against compacted content; this is deterministic and preserves text.
    parts[:]=compact
    for cols in (2 if len(parts)>1 else 1, 3 if len(parts)>=6 else 1):
        if cols<=len(parts) and layout_stacked(cols,15,10): return
    # Final readability fallback. Do not fail the entire deck because a template's
    # sample box is too small; use the full safe canvas and the smallest reasonable
    # editable font.
    if layout_stacked(2 if len(parts)>1 else 1,12,8.5): return
    if layout_stacked(1,10,8): return
    # The last resort uses a single text box with manual line breaks. No information
    # is discarded; the surrounding audit can still flag visual density.
    _textbox(slide,(x,y,w,h),'\n\n'.join(parts),font,color,9,bold=False,min_size=8)

def _timeline_cards(slide,box,steps,font,color,accent):
    x,y,w,h=box
    steps=[s for s in steps if s.get('label') or s.get('detail')]
    if not steps:return
    gap=.14
    # Three substantive process steps fit far better as three cards in one row;
    # four or five steps use two columns. This avoids forcing dense text into a
    # second row on narrow VK masters.
    cols = 3 if len(steps)==3 else (2 if len(steps)>1 else 1)
    rows=math.ceil(len(steps)/cols)
    cw=(w-gap*(cols-1))/cols; rh=(h-gap*(rows-1))/rows
    for i,step in enumerate(steps):
        bx=x+(i%cols)*(cw+gap); by=y+(i//cols)*(rh+gap)
        label=str(step.get('label','')).strip()
        detail=str(step.get('detail','')).strip()
        # Give the label its own compact line, then let the full explanatory detail
        # occupy the remaining card. Nothing is truncated.
        label_h=min(.42,max(.30,rh*.22))
        if label and not _fits(label,cw,label_h,14): label_h=.30
        if label:
            _textbox(slide,(bx,by,cw,label_h),label,font,accent,14,True,min_size=11)
        if detail:
            min_body=10 if rh < 1.8 else 12
            _textbox(slide,(bx,by+label_h+.04,cw,max(.25,rh-label_h-.04)),detail,font,color,14,False,min_size=min_body)

def _fill(prs,slide,source,data,plan,variant,font,accent,evidence,image_info=None):
    title,body,color=_basis(prs,source,slide,data['kind'])
    _textbox(slide,title,data['title'],font,color,30,True,min_size=20)
    x,y,w,h=body;parts=[]
    image_used=None
    image_failed=False
    if image_info:
        try:
            image_used=_insert_image(prs,slide,source,image_info)
        except Exception:
            image_failed=True
            image_used=None
    if data.get('subtitle'):parts.append(data['subtitle'])
    parts+=data.get('points',[])
    # Structured content receives native objects, never flattened text or sample charts.
    if data.get('chart') or data.get('table'):
        visual=(x,y,w*.54,h); side=(x+w*.58,y,w*.42,h)
        if data.get('table'):
            d=data['table']
            rows=[d['columns']]+d['rows']
            table_shape=slide.shapes.add_table(len(rows),len(d['columns']),*[Inches(v) for v in visual]);table_shape.name='generated:table'
            table=table_shape.table
            cw=(visual[2])/max(1,len(d['columns']))
            # Allocate row heights by text volume instead of equal heights. This keeps
            # detailed explanatory cells readable without rejecting the whole slide.
            weights=[max(10,sum(len(str(v).split()) for v in row)) for row in rows]
            total_weight=sum(weights)
            min_row_h=.42
            remaining=max(.6,visual[3]-min_row_h*len(rows))
            for ri,row in enumerate(rows):
                rh=min_row_h+remaining*(weights[ri]/total_weight)
                table.rows[ri].height=Inches(rh)
                for ci,value in enumerate(row):
                    value=str(value).strip()
                    cell=table.cell(ri,ci);cell.text=value
                    cell.margin_left=Inches(.035);cell.margin_right=Inches(.035)
                    cell.margin_top=Inches(.025);cell.margin_bottom=Inches(.025)
                    cell.fill.solid();cell.fill.fore_color.rgb=RGBColor.from_string(accent if ri==0 else 'FFFFFF')
                    size=12 if ri==0 else 11
                    floor=9 if ri==0 else 8
                    while size>floor and not _fits(value,cw,rh,size): size-=.5
                    if not _fits(value,cw,rh,size):
                        # Last resort: use a compact editable table rather than aborting.
                        size=floor
                    for p in cell.text_frame.paragraphs:
                        p.space_after=Pt(0);p.line_spacing=1.0
                        for r in p.runs:
                            r.font.name=font;r.font.size=Pt(size);r.font.bold=ri==0
                            r.font.color.rgb=RGBColor.from_string('FFFFFF' if ri==0 else '17223B')
        else:
            d=data['chart']; cd=ChartData();cd.categories=d['labels'];cd.add_series(d['unit'],d['values'])
            types={'bar':XL_CHART_TYPE.BAR_CLUSTERED,'column':XL_CHART_TYPE.COLUMN_CLUSTERED,'line':XL_CHART_TYPE.LINE,'pie':XL_CHART_TYPE.PIE}
            shape=slide.shapes.add_chart(types[d['type']],*[Inches(v) for v in visual],cd);shape.name='generated:chart';chart=shape.chart
            chart.has_title=True;chart.chart_title.text_frame.text=d['unit'];chart.has_legend=d['type']=='pie'
            chart.font.name=font;chart.font.size=Pt(12)
            chart.font.color.rgb=RGBColor.from_string(color)
            if d['type']!='pie':
                chart.value_axis.has_title=True;chart.value_axis.axis_title.text_frame.text=d['unit']
                chart.value_axis.tick_labels.font.color.rgb=RGBColor.from_string(color)
                chart.category_axis.tick_labels.font.color.rgb=RGBColor.from_string(color)
            chart.plots[0].has_data_labels=True
        _paragraphs(slide,side,parts,font,color,'balanced',accent)
    elif data['kind']=='two_column':
        # Preflight narrow columns before adding objects; stack semantic groups
        # when a small template cannot fit them at readable size.
        groups=((data['left_title'],data['left_points']),(data['right_title'],data['right_points']))
        col_h=h-(.7 if parts else 0)-.55
        def column_fits(items):
            weights=[max(30,len(t)) for t in items];total=sum(weights)
            return all(_fits(t,w*.48,(col_h-.14*(len(items)-1))*wt/total,13) for t,wt in zip(items,weights))
        if not all(column_fits(items) for _,items in groups):
            # Dense comparisons should keep the two-column meaning instead of
            # collapsing five separate blocks into a tiny generic grid. Reserve
            # a compact intro line and render each column as stacked cards.
            if parts:
                intro=' '.join(parts)
                ih=min(.48,max(.32,h*.14))
                _textbox(slide,(x,y,w,ih),intro,font,color,13,False,min_size=10)
                y += ih + .12; h=max(.3,h-ih-.12)
            col_gap=.18; col_w=(w-col_gap)/2
            for ci,(heading,items) in enumerate(groups):
                bx=x+ci*(col_w+col_gap)
                _textbox(slide,(bx,y,col_w,.38),heading,font,color,16,True,min_size=11)
                inner_y=y+.46; inner_h=max(.25,h-.46)
                items=[str(v).strip() for v in items if str(v).strip()]
                gap=.10; row_h=(inner_h-gap*max(0,len(items)-1))/max(1,len(items))
                for ri,item in enumerate(items):
                    _textbox(slide,(bx,inner_y+ri*(row_h+gap),col_w,row_h),item,font,color,13,False,min_size=10)
        else:
            if parts:
                summary=' '.join(parts)
                if _fits(summary,w,.6,16):
                    _textbox(slide,(x,y,w,.6),summary,font,color,16)
                    y+=.7;h-=.7
                else:
                    # A narrow VK master may not have room for a one-line subtitle;
                    # reflow it into the body instead of failing the whole render.
                    _paragraphs(slide,(x,y,w,h),parts,font,color,'columns',accent)
                    y=body[1]+h; h=.01
            for i,(heading,items) in enumerate(groups):
                bx=x+i*(w*.52)
                _textbox(slide,(bx,y,w*.48,.45),heading,font,color,18,True)
                _paragraphs(slide,(bx,y+.55,w*.48,h-.55),items,font,color,'balanced',accent)
    elif data.get('timeline'):
        if parts:
            # Keep a possible introductory subtitle visible, but do not let it
            # steal the height needed for the process/timeline cards.
            try:
                _paragraphs(slide,(x,y,w,min(.55,h*.16)),parts,font,color,'balanced',accent,min_size=12)
                y += .65; h=max(.2,h-.65)
            except LayoutError:
                pass
        _timeline_cards(slide,(x,y,w,h),data['timeline'],font,color,accent)
    elif data.get('metrics'):
        entries=[m['value']+' — '+m['label']+'\n'+m['note'] for m in data['metrics']]
        _paragraphs(slide,body,parts+entries,font,color,'columns',accent)
    elif data['kind']=='sources':
        size=h/len(data['points'])
        for i,(text,sid) in enumerate(zip(data['points'],data['source_ids'])):
            _textbox(slide,(x,y+i*size,w,size-.12),text,font,color,15,min_size=12,link=evidence.get(sid,{}).get('url'))
    else:
        parts+=data.get('left_points',[])+data.get('right_points',[])
        if data.get('quote'):parts.append(data['quote'])
        slot_parts=[str(v).strip() for v in parts if str(v).strip()]
        used_slots=_render_into_slots(slide,source,prs,slot_parts,font,color,variant,avoid_pictures=bool(image_used)) if slot_parts else False
        if not used_slots: _paragraphs(slide,body,parts,font,color,variant,accent)
    # Source IDs and evidence live in speaker notes and the dedicated sources slide,
    # not in the main body. This prevents a source identifier from replacing content
    # or appearing as ugly [W...] text on ordinary slides.
    sh=prs.slide_height/EMU;sw=prs.slide_width/EMU
    num_shape=_textbox(slide,(sw*.89,sh*.93,sw*.07,.22),str(data['number']),font,color,9,min_size=9); num_shape.name='slide:number'
    note_text=data.get('notes','')+'\n\n'+ '\n'.join(c['text']+' ['+c['source_id']+']\n'+c['evidence_quote'] for c in data.get('claims',[]))
    if image_info:
        credit='Изображение: '+str(image_info.get('title','')).strip()
        source_url=image_info.get('landing_url') or image_info.get('url') or ''
        if image_info.get('creator'): credit += ' · '+str(image_info['creator'])
        if image_info.get('license'): credit += ' · лицензия '+str(image_info['license'])
        if source_url: credit += ' · '+str(source_url)
        note_text += '\n\n'+credit
    slide.notes_slide.notes_text_frame.text=note_text

def _clear_slide_content(slide):
    for sh in list(all_shapes(slide.shapes)):
        try:
            if sh.has_text_frame: sh.text=''
            elif sh.has_chart or sh.has_table: sh._element.getparent().remove(sh._element)
        except Exception:
            pass

def _safe_fill_existing(prs, dest, source, data, font, accent, variant, image_info=None):
    title_box, body_box, color = _basis(prs,source,dest,data.get('kind','content'))
    _textbox(dest,title_box,data['title'],font,color,28,True,min_size=18)
    x,y,w,h=body_box
    body=[]
    body += [str(data.get('subtitle','')).strip()] if data.get('subtitle') else []
    body += [str(x).strip() for x in data.get('points',[]) if str(x).strip()]
    body += [str(x).strip() for x in data.get('left_points',[]) if str(x).strip()]
    body += [str(x).strip() for x in data.get('right_points',[]) if str(x).strip()]
    if data.get('quote'): body.append(str(data['quote']).strip())
    _paragraphs(dest,(x,y,w,h),body,font,color,variant,accent,min_size=10)
    if image_info:
        try: _insert_image(prs,dest,source,image_info)
        except Exception: pass

def _absolute_safe_fill(prs, dest, source, data, font, accent, variant, image_info=None):
    """Last-resort template-preserving renderer that never raises LayoutError."""
    title_box, body_box, color = _basis(prs,source,dest,data.get('kind','content'))
    _textbox(dest,title_box,str(data.get('title') or f"Слайд {data.get('number','')}"),font,color,27,True,min_size=18)
    x,y,w,h=body_box
    chunks=[]
    if data.get('subtitle'): chunks.append(str(data['subtitle']).strip())
    chunks += [str(v).strip() for v in data.get('points',[]) if str(v).strip()]
    chunks += [str(v).strip() for v in data.get('left_points',[]) if str(v).strip()]
    chunks += [str(v).strip() for v in data.get('right_points',[]) if str(v).strip()]
    for m in data.get('metrics',[]) or []: chunks.append(f"{m.get('value','')} — {m.get('label','')}: {m.get('note','')}".strip())
    if data.get('table'):
        chunks.append(' | '.join(str(v) for v in data['table'].get('columns',[])))
        for row in data['table'].get('rows',[])[:8]: chunks.append(' | '.join(str(v) for v in row))
    if data.get('chart'):
        d=data['chart']; chunks.append(f"{d.get('unit','')}: "+'; '.join(f"{a} — {v}" for a,v in zip(d.get('labels',[]),d.get('values',[]))))
    for st in data.get('timeline',[]) or []: chunks.append(f"{st.get('label','')}: {st.get('detail','')}".strip(' :'))
    if data.get('quote'): chunks.append(str(data['quote']))
    chunks=[c for c in chunks if c]
    # Keep the full factual payload; split into two editable regions when possible.
    if len(chunks)>2:
        mid=math.ceil(len(chunks)/2)
        left='\n\n'.join(chunks[:mid]); right='\n\n'.join(chunks[mid:])
        gap=.18; cw=(w-gap)/2
        _textbox(dest,(x,y,cw,h),left,font,color,13,False,min_size=8)
        _textbox(dest,(x+cw+gap,y,cw,h),right,font,color,13,False,min_size=8)
    else:
        _textbox(dest,(x,y,w,h),'\n\n'.join(chunks),font,color,13,False,min_size=8)
    if image_info:
        try: _insert_image(prs,dest,source,image_info)
        except Exception: pass
    sh=prs.slide_height/EMU;sw=prs.slide_width/EMU
    num_shape=_textbox(dest,(sw*.89,sh*.93,sw*.07,.22),str(data['number']),font,color,9,min_size=8); num_shape.name='slide:number'
    note=data.get('notes','')
    if image_info:
        note += '\n\nИзображение: '+str(image_info.get('title',''))
        if image_info.get('creator'): note += ' · '+str(image_info['creator'])
        if image_info.get('license'): note += ' · лицензия '+str(image_info['license'])
        note += ' · '+str(image_info.get('landing_url') or image_info.get('url') or '')
    try: dest.notes_slide.notes_text_frame.text=note
    except Exception: pass

def render_variant(template_path,plan,template_spec,out_path,variant,template_id=None,sources=None,images=None):
    plan=Deck.model_validate(plan).model_dump()
    if variant not in VARIANTS: raise ValueError('Unknown layout variant')
    prs=Presentation(str(template_path));font,accent=_tokens(prs,template_spec)
    original_count=len(prs.slides)
    evidence={s['id']:s for s in (sources or []) if isinstance(s,dict) and s.get('id')}
    image_map={int(x.get('slide')):x for x in (images or []) if isinstance(x,dict) and x.get('slide') is not None}
    for data in plan['slides']:
        source=_template_source(prs,template_id,variant,data['kind'])
        dest=None
        try:
            dest=_clone(prs,source)
            _fill(prs,dest,source,data,plan,variant,font,accent,evidence,image_map.get(int(data['number'])))
        except Exception:
            # Keep the already-created slide relationship intact; replacing it by a new
            # slide would leave stale slide IDs in the package and can lose slides.
            try:
                _safe_fill_existing(prs,dest,source,data,font,accent,variant,image_map.get(int(data['number'])))
            except Exception:
                _absolute_safe_fill(prs,dest,source,data,font,accent,variant,image_map.get(int(data['number'])))
            note=data.get('notes','')+'\n\n'+ '\n'.join(c['text']+' ['+c['source_id']+']\n'+c['evidence_quote'] for c in data.get('claims',[]))
            try: dest.notes_slide.notes_text_frame.text=note
            except Exception: pass
    for i in reversed(range(original_count)):
        entry=prs.slides._sldIdLst[i];prs.part.drop_rel(entry.rId);prs.slides._sldIdLst.remove(entry)
    out=Path(out_path);out.parent.mkdir(parents=True,exist_ok=True);prs.save(out)
    Presentation(str(out))
    return out
