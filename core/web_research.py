"""Mandatory web research: discover, rank and fetch real pages; snippets are never evidence."""
from __future__ import annotations
import re, time, socket, ipaddress, hashlib, io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin, parse_qs, quote_plus, unquote
import requests

BAD_HOSTS = {
    'facebook.com','instagram.com','tiktok.com','x.com','twitter.com',
    'pinterest.com','linkedin.com'
}
# Search engines and their result/help pages are never accepted as evidence.
SEARCH_ENGINE_HOSTS = {
    'google.com','www.google.com','google.co.uk','google.ru',
    'bing.com','www.bing.com',
    'duckduckgo.com','html.duckduckgo.com','lite.duckduckgo.com','api.duckduckgo.com',
    'brave.com','search.brave.com',
    'yahoo.com','search.yahoo.com',
}
SEARCH_UI_MARKERS = (
    'к основному контенту', 'справка - google поиск', 'войти', 'справочный центр',
    'улучшите аккаунт google', 'попробуйте следующее', 'отправить отзыв',
    'search help', 'google search', 'sign in', 'help center'
)
PREFERRED_SUFFIXES = ('.gov', '.gov.ru', '.edu', '.ac.uk', '.edu.ru', '.org')
LOW_VALUE_PATHS = ('/search', '/tag/', '/category/', '/login', '/signup', '/about')
JINA_READER_BASE = 'https://r.jina.ai/'

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]; self.links=[]; self.meta={}; self.title=[]; self.in_title=False; self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ('script','style','nav','footer','noscript','svg'): self.skip+=1
        if tag=='title': self.in_title=True
        if tag=='a' and a.get('href'): self.links.append(a['href'])
        if tag=='meta': self.meta[a.get('property',a.get('name','')).lower()]=a.get('content','')
    def handle_endtag(self,tag):
        if tag in ('script','style','nav','footer','noscript','svg'): self.skip=max(0,self.skip-1)
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if not self.skip and data.strip(): self.parts.append(data.strip())
        if self.in_title: self.title.append(data)

class SearchResultParser(HTMLParser):
    """Extract result links from several common search-engine HTML layouts."""
    TITLE_CLASSES = {'result__a', 'result-link', 'result-title', 'result-header'}
    SNIPPET_CLASSES = {'result__snippet', 'result-snippet', 'snippet', 'description'}
    def __init__(self):
        super().__init__()
        self.results=[]; self.current=None; self.mode=None

    @staticmethod
    def _classes(attrs):
        return set((dict(attrs).get('class') or '').split())

    def handle_starttag(self,tag,attrs):
        a=dict(attrs); classes=self._classes(attrs); href=a.get('href','')
        if tag=='a' and href and classes & self.TITLE_CLASSES:
            if self.current and self.current.get('url'):
                self.results.append(self.current)
            self.current={'url':href,'title':'','snippet':''}
            self.mode='title'
            return
        if self.current is not None and classes & self.SNIPPET_CLASSES:
            self.mode='snippet'

    def handle_endtag(self,tag):
        if self.current is None: return
        if self.mode=='title' and tag=='a': self.mode=None
        elif self.mode=='snippet' and tag in ('div','span','a','p'): self.mode=None

    def handle_data(self,data):
        if self.current is None or not data.strip(): return
        if self.mode=='title': self.current['title'] += ' '+data.strip()
        elif self.mode=='snippet': self.current['snippet'] += ' '+data.strip()

    def close(self):
        super().close()
        if self.current:
            self.results.append(self.current)
            self.current=None


def _absolute_search_url(url, base=''):
    url=unescape((url or '').strip())
    if url.startswith('//'): return 'https:'+url
    if base: return urljoin(base,url)
    return url


def _parse_bing_rss(xml):
    import xml.etree.ElementTree as ET
    root=ET.fromstring(xml)
    out=[]
    for item in root.findall('.//item'):
        title=' '.join((item.findtext('title') or '').split())
        link=''.join(item.findtext('link') or '').strip()
        snippet=' '.join((item.findtext('description') or '').split())
        if link: out.append({'url':link,'title':title,'snippet':snippet})
    return out


def _parse_google_html(html):
    # Google wraps ordinary results as /url?q=... in a number of layouts.
    out=[]; seen=set()
    for m in re.finditer(r'href=[\"\'](?:/url\?q=|/url\?sa=t&url=)([^\"\'&]+)',html,re.I):
        u=unquote(m.group(1))
        if u in seen or not u.startswith(('http://','https://')): continue
        seen.add(u); out.append({'url':u,'title':'','snippet':''})
    return out


def _parse_generic_external_links(html, base):
    # Conservative fallback for engines whose CSS classes changed.
    out=[]; seen=set()
    for m in re.finditer(r'<a[^>]+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>',html,re.I|re.S):
        u=_absolute_search_url(m.group(1),base)
        host=_host(u)
        if not u.startswith(('http://','https://')) or not host or host in {'google.com','www.google.com','bing.com','www.bing.com','duckduckgo.com','html.duckduckgo.com','lite.duckduckgo.com','search.brave.com','brave.com'}:
            continue
        text=re.sub(r'<[^>]+>',' ',m.group(2)); text=' '.join(unescape(text).split())
        if len(text)<8 or u in seen: continue
        seen.add(u); out.append({'url':u,'title':text[:300],'snippet':''})
    return out


def _request_search(url, deadline, accept='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'):
    left=deadline-time.monotonic()
    if left<=0: raise TimeoutError('Research deadline')
    headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36',
             'Accept':accept,'Accept-Language':'ru-RU,ru;q=0.9,en;q=0.8'}
    with requests.Session() as client:
        # Honor system HTTP(S)_PROXY settings when present; disabling them breaks
        # many university/corporate networks and is not needed for public search.
        client.trust_env=True
        r=client.get(url,headers=headers,timeout=min(12,left),allow_redirects=True)
        r.raise_for_status()
        return r.text

def _request_jina(url, deadline):
    left=deadline-time.monotonic()
    if left<=0: raise TimeoutError('Research deadline')
    target=JINA_READER_BASE + url
    headers={'User-Agent':'Digital-Presentation-Designer/7.2','Accept':'text/plain,text/markdown;q=0.9,*/*;q=0.8','Accept-Language':'ru-RU,ru;q=0.9,en;q=0.8'}
    with requests.Session() as client:
        client.trust_env=True
        r=client.get(target,headers=headers,timeout=min(18,left),allow_redirects=True)
        r.raise_for_status()
        return r.text

def _parse_markdown_search_results(text):
    out=[];seen=set()
    for m in re.finditer(r'\[([^\]]{3,300})\]\((https?://[^\)\s]+)\)', text or ''):
        title=' '.join(unescape(m.group(1)).split())
        url=unescape(m.group(2).rstrip(').,;'))
        host=_host(url)
        if not host or host in BAD_HOSTS or host in {h.removeprefix('www.') for h in SEARCH_ENGINE_HOSTS}:
            continue
        if url in seen: continue
        seen.add(url)
        out.append({'url':url,'title':title[:300],'snippet':''})
    return out


def _provider_candidates(provider, effective, deadline):
    if provider=='ddg_html':
        html=_request_search('https://html.duckduckgo.com/html/?q='+quote_plus(effective),deadline)
        parser=SearchResultParser(); parser.feed(html); parser.close(); return parser.results
    if provider=='ddg_lite':
        html=_request_search('https://lite.duckduckgo.com/lite/?q='+quote_plus(effective),deadline)
        parser=SearchResultParser(); parser.feed(html); parser.close()
        return parser.results or _parse_generic_external_links(html,'https://lite.duckduckgo.com/lite/')
    if provider=='bing_rss':
        xml=_request_search('https://www.bing.com/search?format=rss&q='+quote_plus(effective),deadline,accept='application/xml,text/xml,*/*')
        return _parse_bing_rss(xml)
    if provider=='google':
        html=_request_search('https://www.google.com/search?hl=en&gbv=1&q='+quote_plus(effective),deadline)
        out=_parse_google_html(html)
        if not out:
            parser=SearchResultParser(); parser.feed(html); parser.close(); out=parser.results
        return out or _parse_generic_external_links(html,'https://www.google.com/')
    if provider=='brave':
        html=_request_search('https://search.brave.com/search?q='+quote_plus(effective)+'&source=web',deadline)
        parser=SearchResultParser(); parser.feed(html); parser.close()
        return parser.results or _parse_generic_external_links(html,'https://search.brave.com/')
    if provider=='yandex':
        html=_request_search('https://yandex.ru/search/?text='+quote_plus(effective),deadline)
        parser=SearchResultParser(); parser.feed(html); parser.close()
        return parser.results or _parse_generic_external_links(html,'https://yandex.ru/search/')
    if provider in ('jina_google','jina_bing','jina_yandex'):
        search_base={
            'jina_google':'https://www.google.com/search?hl=en&gbv=1&num=10&q=',
            'jina_bing':'https://www.bing.com/search?count=10&q=',
            'jina_yandex':'https://yandex.ru/search/?text=',
        }
        text=_request_jina(search_base[provider]+quote_plus(effective),deadline)
        return _parse_markdown_search_results(text)
    if provider=='ddg_api':
        import json as _json
        raw=_request_search('https://api.duckduckgo.com/?q='+quote_plus(effective)+'&format=json&no_html=1&skip_disambig=1',deadline,accept='application/json,*/*')
        data=_json.loads(raw)
        out=[]
        if data.get('AbstractURL'):
            out.append({'url':data['AbstractURL'],'title':data.get('Heading',''),'snippet':data.get('AbstractText','')})
        def walk(items):
            for item in items or []:
                if item.get('FirstURL'):
                    out.append({'url':item['FirstURL'],'title':item.get('Text',''),'snippet':item.get('Text','')})
                walk(item.get('Topics'))
        walk(data.get('RelatedTopics'))
        return out
    raise ValueError('Unknown search provider')

def public_url(url):
    # Keep URL validation strict about schemes/credentials/search-engine pages,
    # but do not make DNS resolution a hard prerequisite: university/corporate
    # networks may resolve hosts through a proxy while local DNS is unavailable.
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise ValueError('Допускаются публичные HTTP(S) ссылки.')
    host=(p.hostname or '').lower().removeprefix('www.')
    if host in {h.removeprefix('www.') for h in SEARCH_ENGINE_HOSTS}:
        raise ValueError('Страница поисковой системы не является источником.')
    try:
        ip=ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError('Локальные и служебные адреса не загружаются.')
    except ValueError:
        # Hostname: DNS is intentionally checked only when the runtime can resolve it.
        # The actual HTTP request and the Jina fallback remain the source of truth.
        try:
            addresses=socket.getaddrinfo(host,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
            if addresses and not any(ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError('Локальные и служебные адреса не загружаются.')
        except OSError:
            pass
    return url

def _clean_ddg_url(url):
    if url.startswith('//'): url='https:'+url
    q=parse_qs(urlparse(url).query)
    return unescape(q.get('uddg',[url])[0])

def _host(url):
    return (urlparse(url).hostname or '').lower().removeprefix('www.')

def _host_allowed(host,domain=''):
    if not host or host in BAD_HOSTS: return False
    domain=(domain or '').strip().lower().removeprefix('www.')
    return not domain or host==domain or host.endswith('.'+domain)

def _score_result(item,job):
    url=item['url']; host=_host(url)
    qwords=set(re.findall(r'[a-zа-яё0-9]{4,}', (job.get('query','')+' '+item.get('title','')+' '+item.get('snippet','')).lower()))
    titlewords=set(re.findall(r'[a-zа-яё0-9]{4,}', item.get('title','').lower()))
    snippetwords=set(re.findall(r'[a-zа-яё0-9]{4,}', item.get('snippet','').lower()))
    overlap=len(qwords & (titlewords|snippetwords))
    score=overlap*3
    if host.endswith(PREFERRED_SUFFIXES): score+=4
    if any(k in urlparse(url).path.lower() for k in ('report','publication','research','article','study','stat','data','document','news')): score+=2
    if any(k in urlparse(url).path.lower() for k in LOW_VALUE_PATHS): score-=3
    if len(item.get('title','').strip())<12: score-=2
    return score

def search_job(job,deadline):
    query=job['query'].strip()
    domain=job.get('domain','').strip().lower()
    effective=('site:'+domain+' '+query) if domain else query
    if deadline-time.monotonic()<=0: raise TimeoutError('Research deadline')
    providers=('jina_google','jina_bing','jina_yandex','yandex','ddg_html','bing_rss','ddg_lite','google','brave','ddg_api')
    all_candidates=[]; errors=[]
    for provider in providers:
        if deadline-time.monotonic()<=1: break
        try:
            candidates=_provider_candidates(provider,effective,deadline)
            for item in candidates[:12]:
                u=_clean_ddg_url(_absolute_search_url(item.get('url','')))
                h=_host(u)
                if not u.startswith(('http://','https://')) or not h or not _host_allowed(h,domain):
                    continue
                enriched={**item,'url':u,'provider':provider}
                enriched['score']=_score_result(enriched,job)
                all_candidates.append(enriched)
            # Two good independent providers are enough for a query once we have usable links.
            jina_usable=sum(1 for c in all_candidates if c.get('provider') in ('jina_google','jina_bing','jina_yandex'))
            if len(all_candidates)>=6 and jina_usable>=3: break
        except Exception as exc:
            errors.append(provider+': '+type(exc).__name__)
    all_candidates.sort(key=lambda x:(x.get('score',0),len(x.get('snippet',''))),reverse=True)
    # Dedupe the result list while keeping search-engine diversity.
    unique=[]; seen=set()
    for item in all_candidates:
        key=(urlparse(item['url']).hostname or '',urlparse(item['url']).path.rstrip('/'))
        if key in seen: continue
        seen.add(key); unique.append(item)
        if len(unique)>=8: break
    if not unique and errors:
        raise RuntimeError('Все поисковые провайдеры недоступны: '+', '.join(errors))
    return {'job':job,'candidates':unique}

def fetch(url,deadline,expect_html=True):
    # Direct fetch first; if the local network/proxy/JS blocks it, use Jina Reader
    # as a server-side browser/extractor. This keeps the source URL unchanged and
    # removes navigation boilerplate before it reaches the LLM.
    direct_error=None
    try:
        public_url(url)
        with requests.Session() as client:
            client.trust_env=True
            current=url
            for _ in range(5):
                left=deadline-time.monotonic()
                if left<=0: raise TimeoutError('Research deadline')
                with client.get(current,headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36',
                    'Accept':'text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.7',
                    'Accept-Language':'ru-RU,ru;q=0.9,en;q=0.8'},timeout=min(10,left),allow_redirects=False,stream=True) as r:
                    if 300<=r.status_code<400:
                        location=r.headers.get('Location')
                        if not location: raise ValueError('Redirect without Location')
                        current=urljoin(current,location);continue
                    r.raise_for_status()
                    chunks=[];size=0
                    for chunk in r.iter_content(32768):
                        size+=len(chunk)
                        if size>8_000_000 or time.monotonic()>deadline: raise ValueError('Source size/time limit')
                        chunks.append(chunk)
                    data=b''.join(chunks);ct=r.headers.get('Content-Type','').lower()
                    if expect_html and not any(t in ct for t in ('html','pdf','text/plain')):
                        raise ValueError('Unsupported web source content type: '+ct)
                    return current,data,ct
            raise ValueError('Too many redirects')
    except Exception as exc:
        direct_error=exc
    # Server-side fallback. Only use it for public HTTP(S) targets; it is not a way
    # to access local services because public_url still rejects literal private IPs.
    left=deadline-time.monotonic()
    if left<=0: raise direct_error or TimeoutError('Research deadline')
    try:
        text=_request_jina(url,deadline)
        if len(text.strip())<300: raise ValueError('Jina Reader returned too little source text')
        return url,text.encode('utf-8'), 'text/plain; proxy=jina-reader'
    except Exception as proxy_exc:
        raise ValueError('Прямое чтение источника не удалось ('+type(direct_error).__name__+'); Jina Reader тоже недоступен ('+type(proxy_exc).__name__+').') from proxy_exc

def _looks_like_search_ui(text, title=''):
    t=' '.join(str(text or '').split()).casefold()
    title_norm=' '.join(str(title or '').split()).casefold()
    if any(marker in title_norm for marker in ('google поиск','google search','справка - google')):
        return True
    hits=sum(1 for marker in SEARCH_UI_MARKERS if marker in t)
    return hits >= 2 or (hits >= 1 and t.count('google') >= 4)


def verified_page(url,deadline,search_meta=None):
    final,data,content_type=fetch(url,deadline)
    if 'pdf' in content_type or final.lower().split('?',1)[0].endswith('.pdf'):
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            text=' '.join((page.extract_text() or '') for page in reader.pages[:25])
        except Exception as exc:
            raise ValueError('PDF text extraction failed: '+type(exc).__name__) from exc
        title=(search_meta or {}).get('title') or urlparse(final).path.rsplit('/',1)[-1] or urlparse(final).hostname
    elif 'text/plain' in content_type:
        text=data.decode('utf-8',errors='replace')
        # Jina Reader returns clean Markdown/plain text. Strip leading metadata and
        # markdown link wrappers but preserve the body itself.
        if 'proxy=jina-reader' in content_type:
            md_links=_parse_markdown_search_results(text)
            if md_links and not search_meta:
                # This should only happen for accidental search-page fetches; reject it.
                raise ValueError('Reader returned a search-results page, not a source page.')
            text=re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\1', text)
            title=(search_meta or {}).get('title') or next((line.lstrip('# ').strip() for line in text.splitlines() if line.strip().startswith('#')), '') or urlparse(final).hostname
        else:
            title=(search_meta or {}).get('title') or urlparse(final).hostname
    else:
        encoding='utf-8'
        # Decode HTML using the response's charset when available; utf-8 is a safe fallback.
        raw=data.decode(encoding,errors='replace')
        page=Page(); page.feed(raw); page.close()
        text=' '.join(page.parts)
        title=page.meta.get('og:title') or ''.join(page.title).strip() or (search_meta or {}).get('title') or urlparse(final).hostname
    text=' '.join(text.split())
    if len(text)<300: raise ValueError('Too little source text')
    forbidden_search={h.removeprefix('www.') for h in SEARCH_ENGINE_HOSTS}
    if _host(final) in forbidden_search:
        raise ValueError('Поисковая выдача не может быть веб-источником.')
    if _looks_like_search_ui(text, title):
        raise ValueError('Страница похожа на страницу результатов/справки поисковика и не принята как источник.')
    excerpt=text[:12000]
    return {
        'id':'W'+hashlib.sha256(final.encode()).hexdigest()[:10],
        'kind':'web','url':final,
        'title':title,
        'site_name':(search_meta or {}).get('site_name',''),'author':'',
        'published_at':'',
        'accessed_at':datetime.now(timezone.utc).isoformat(),'verified':True,
        'verification':'page_fetched; search_snippet_not_used_as_evidence',
        'text':excerpt,'excerpt_truncated':len(text)>len(excerpt),
        'content_type':content_type,
        'content_sha256':hashlib.sha256(data).hexdigest(),
        'search_query':(search_meta or {}).get('query',''),
        'search_reason':(search_meta or {}).get('reason',''),
        'search_score':(search_meta or {}).get('score',0),
        'search_provider':(search_meta or {}).get('provider',''),
    }

def _plan_fallback(brief):
    """Deterministic multi-query research plan; no LLM is needed for web discovery."""
    words = ' '.join(re.findall(r'[a-zа-яё0-9]{4,}', brief.lower())[:18]).strip()
    if not words:
        words = 'тема презентации'
    return [
        {'query': words + ' официальные данные статистика отчет', 'domain': '', 'reason': 'Официальные данные и отчёт'},
        {'query': words + ' официальный сайт документы исследования', 'domain': '', 'reason': 'Первичный/официальный источник'},
        {'query': words + ' академическое исследование научная статья', 'domain': '', 'reason': 'Академическое подтверждение'},
        {'query': words + ' исследование pdf данные результаты', 'domain': '', 'reason': 'Полный исследовательский документ'},
        {'query': words + ' trend statistics report data', 'domain': '', 'reason': 'Количественные данные и динамика'},
        {'query': words + ' methodology analysis evidence', 'domain': '', 'reason': 'Методология и интерпретация'},
    ]

def research(brief,source_text='',max_jobs=8,budget_seconds=150, *, session=None):
    start=time.monotonic(); deadline=start+budget_seconds
    sources=[]; warnings=[]; jobs=[]

    explicit_urls=list(dict.fromkeys(re.findall(r'https?://[^\s<>\]\)]+',brief)))
    if explicit_urls:
        jobs=[{'query':'direct URL','domain':_host(u),'reason':'User-supplied direct source'} for u in explicit_urls[:8]]
        discovered=[{'url':u,'title':'','snippet':'','score':10} for u in explicit_urls[:8]]
    else:
        jobs=_plan_fallback(brief)[:min(max_jobs,4)]
        discovered=[]
        # Search in parallel so the quality of the web sweep does not depend on one slow domain.
        workers=min(4,max(1,len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(search_job,job,deadline) for job in jobs]
            for f in as_completed(futures):
                try:
                    data=f.result()
                    for c in data['candidates']:
                        discovered.append({**c,'reason':data['job'].get('reason',''),'query':data['job'].get('query','')})
                except Exception:
                    warnings.append('Один из веб-поисков не завершился.')
    # Deduplicate by final hostname+path and keep diverse sources.
    discovered.sort(key=lambda x:(x.get('score',0),len(x.get('snippet',''))),reverse=True)
    seen=set(); selected=[]
    for c in discovered:
        url=c['url']
        host=_host(url)
        key=(host,urlparse(url).path.rstrip('/').lower())
        if key in seen: continue
        if host in BAD_HOSTS or host in {h.removeprefix('www.') for h in SEARCH_ENGINE_HOSTS}: continue
        seen.add(key); selected.append(c)
        if len(selected)>=max(10,max_jobs): break

    # Fetch a broader candidate set, then retain the strongest unique sources.
    fetched=[]
    with ThreadPoolExecutor(max_workers=min(6,max(1,len(selected)))) as pool:
        future_map={pool.submit(verified_page,c['url'],deadline,c):c for c in selected[:max(8,max_jobs+1)]}
        for f in as_completed(future_map):
            try:
                item=f.result()
                fetched.append(item)
            except Exception as exc:
                c=future_map[f]
                warnings.append(f"Не удалось загрузить {c.get('url','')}: {type(exc).__name__}")
    # Prefer evidence diversity while retaining high-scoring pages.
    fetched.sort(key=lambda s:(s.get('search_score',0),len(s.get('text',''))),reverse=True)
    hosts=set()
    for item in fetched:
        host=_host(item['url'])
        # Avoid filling the set with near-identical pages from one host.
        if host in hosts and len(sources)<4: continue
        sources.append(item); hosts.add(host)
        if len(sources)>=max_jobs: break

    if not sources:
        warnings.append('Проверенных веб-страниц нет после поиска и загрузки кандидатов. Генератор продолжит работу с локальным контекстом или резервным режимом LLM.')
    return {
        'jobs':jobs,'results':[],'sources':sources,
        'domains':sorted({urlparse(s['url']).hostname for s in sources}),
        'summary':'',
        'warnings':warnings,
        'elapsed_seconds':round(time.monotonic()-start,2)
    }
