"""Best-effort topical image discovery from openly licensed media.

Images are optional enrichment: if the network is unavailable, generation continues
without them. Openverse is used because it indexes openly licensed media and exposes
an unauthenticated image search endpoint.
"""
from __future__ import annotations
import hashlib, io, re, time, os
from pathlib import Path
from urllib.parse import quote_plus
import requests
from PIL import Image, ImageOps

from .image_generation import generate_image, is_enabled

API = 'https://api.openverse.org/v1/images/'
COMMONS_API = 'https://commons.wikimedia.org/w/api.php'
UA = 'Digital-Presentation-Designer/7.4'

def _query_terms(text: str) -> str:
    words = re.findall(r'[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9-]{2,}', text or '')
    stop = {'презентация','слайд','сделай','тема','система','информация','основные','важные','данные'}
    out=[]
    for w in words:
        if w.casefold() in stop or w.casefold() in {x.casefold() for x in out}:
            continue
        out.append(w)
        if len(out)>=9: break
    return ' '.join(out) or 'business technology'

def search_images(query, limit=6, timeout=8):
    params={'q':query,'page_size':limit,'mature':'false'}
    headers={'User-Agent':UA,'Accept':'application/json'}
    try:
        r=requests.get(API,params=params,headers=headers,timeout=timeout)
        r.raise_for_status(); data=r.json()
    except Exception:
        return []
    out=[]
    for item in data.get('results',[]) or []:
        url=item.get('url') or ''
        thumb=item.get('thumbnail') or ''
        if not url and not thumb: continue
        out.append({
            'id': str(item.get('id') or hashlib.sha1((url or thumb).encode()).hexdigest()[:12]),
            'title': ' '.join(str(item.get('title') or '').split())[:220],
            'url': url,
            'thumbnail': thumb,
            'creator': ' '.join(str(item.get('creator') or '').split())[:160],
            'license': str(item.get('license') or ''),
            'license_version': str(item.get('license_version') or ''),
            'landing_url': item.get('foreign_landing_url') or item.get('detail_url') or '',
            'width': int(item.get('width') or 0),
            'height': int(item.get('height') or 0),
            'source': str(item.get('source') or 'Openverse'),
        })
    return out

def search_wikimedia(query, limit=6, timeout=8):
    params={
        'action':'query','generator':'search','gsrsearch':query,'gsrnamespace':'6','gsrlimit':str(limit),
        'prop':'imageinfo|info','iiprop':'url|mime|size','iiurlwidth':'1800','inprop':'url',
        'format':'json','formatversion':'2'
    }
    try:
        r=requests.get(COMMONS_API,params=params,headers={'User-Agent':UA,'Accept':'application/json'},timeout=timeout)
        r.raise_for_status(); data=r.json()
    except Exception:
        return []
    out=[]
    for page in data.get('query',{}).get('pages',[]) or []:
        info=(page.get('imageinfo') or [{}])[0]
        url=info.get('thumburl') or info.get('url') or ''
        if not url: continue
        out.append({
            'id':str(page.get('pageid') or hashlib.sha1(url.encode()).hexdigest()[:12]),
            'title':str(page.get('title') or '').removeprefix('File:'),
            'url':url,'thumbnail':url,'creator':'Wikimedia Commons','license':'See source page',
            'license_version':'','landing_url':f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{quote_plus(str(page.get('title') or '').removeprefix('File:'))}",
            'width':int(info.get('width') or 0),'height':int(info.get('height') or 0),'source':'Wikimedia Commons'
        })
    return out


def _download(url, out, timeout=10):
    if not url: return None
    try:
        r=requests.get(url,headers={'User-Agent':UA,'Accept':'image/avif,image/webp,image/png,image/jpeg,*/*;q=0.7'},timeout=timeout)
        r.raise_for_status()
        if len(r.content)>12_000_000: return None
        img=Image.open(io.BytesIO(r.content)).convert('RGB')
        if img.width<320 or img.height<200: return None
        # Normalize to a PPTX-safe JPEG once, so SVG/WEBP/browser-only formats never
        # leak into python-pptx and every template receives the same raster asset.
        img.thumbnail((2200,1400),Image.Resampling.LANCZOS)
        canvas=ImageOps.exif_transpose(img)
        canvas.save(out,'JPEG',quality=90,optimize=True)
        return out
    except Exception:
        return None

def _eligible_slide(slide):
    kind=slide.get('kind','')
    if kind in {'title','sources','table','chart','metrics'}: return False
    text=' '.join([str(slide.get('title','')),str(slide.get('subtitle','')),str(slide.get('quote',''))])
    if not text.strip(): return False
    # Visual-heavy narrative slides benefit most from an image.
    return kind in {'title','content','two_column','quote','timeline','process','summary','section'}

def collect_images(brief, plan, out_dir, max_images=5, budget_seconds=18, mode=None):
    out_dir=Path(out_dir); out_dir.mkdir(parents=True,exist_ok=True)
    start=time.monotonic(); result=[]; seen=set(); warnings=[]
    slides=[s for s in plan.get('slides',[]) if _eligible_slide(s)]
    requested_mode=(mode or os.getenv('IMAGE_MODE','retrieve')).strip().lower()
    t2i_count=0
    if requested_mode in {'text_to_image','t2i','generate','generated'} and not os.getenv('HF_TOKEN','').strip():
        warnings.append('Text-to-image выбран, но HF_TOKEN не задан; использован retrieval fallback.')
    # For the star task we can generate up to three images. Retrieval remains the
    # safe fallback whenever the optional text-to-image provider is unavailable.
    for slide in slides[:max_images]:
        if time.monotonic()-start>budget_seconds: break
        body=' '.join(str(x) for x in (slide.get('points',[]) or [])[:2])
        source_prompt=' '.join([brief,str(slide.get('title','')),str(slide.get('subtitle','')),body])
        if is_enabled(requested_mode) and t2i_count<3:
            path=out_dir/f"slide_{int(slide['number']):02d}_generated.jpg"
            try:
                generated=generate_image(
                    "Editorial presentation illustration, no text, no logos, professional corporate style, "
                    "visually explaining: "+source_prompt, path, timeout=max(20,min(45,int(budget_seconds))),
                )
                generated['slide']=int(slide['number'])
                generated['title']=slide.get('title','')
                result.append(generated)
                t2i_count+=1
                continue
            except Exception as exc:
                warnings.append(f"Text-to-image fallback for slide {slide.get('number')}: {type(exc).__name__}")
        query=_query_terms(source_prompt)
        remaining_budget=max(4,min(8,budget_seconds-max(0,time.monotonic()-start)))
        candidates=search_images(query,limit=6,timeout=remaining_budget)
        if not candidates:
            candidates=search_wikimedia(query,limit=6,timeout=remaining_budget)
        pick=None
        for c in candidates:
            key=(c.get('url') or c.get('thumbnail') or c.get('id','')).split('?')[0]
            if key in seen: continue
            if c.get('width') and c.get('height') and c['width']<500 and c['height']<300: continue
            pick=c;seen.add(key);break
        if not pick: continue
        path=out_dir/f"slide_{int(slide['number']):02d}.jpg"
        if not _download(pick.get('url') or pick.get('thumbnail'),path):
            if not _download(pick.get('thumbnail'),path): continue
        result.append({
            'slide':int(slide['number']),'path':str(path),'title':pick.get('title',''),
            'creator':pick.get('creator',''),'license':pick.get('license',''),
            'license_version':pick.get('license_version',''),'source':pick.get('source','Openverse'),
            'url':pick.get('url',''),'landing_url':pick.get('landing_url',''),
        })
    providers=sorted(set(str(x.get('source','Openverse')) for x in result))
    if t2i_count:
        providers.insert(0,'Hugging Face Inference Providers')
    return {'items':result,'elapsed_seconds':round(time.monotonic()-start,2),'provider':'+'.join(dict.fromkeys(providers)) if providers else ('Hugging Face / Openverse' if requested_mode not in ('retrieve','off') else 'Openverse/Wikimedia Commons'),'warnings':warnings,'mode':requested_mode}
