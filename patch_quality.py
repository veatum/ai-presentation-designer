from pathlib import Path
p=Path('/mnt/data/workfix/core/quality.py')
s=p.read_text()
# Replace _numeric_quote function
start=s.index('def _numeric_quote(number, sources):')
end=s.index('\ndef _visible_numeric_parts', start)
new=r'''def _numeric_quote(number, sources, preferred_source_ids=None, slide_text=''):
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
'''
s=s[:start]+new+s[end:]
# Replace normalize block around numeric evidence
old="""        # Every visible numeric value must have matching numeric evidence.\n        evidence_text=' '.join(c.get('evidence_quote','') for c in slide['claims'])\n        for part in _visible_numeric_parts(slide):\n            missing=numbers(part)-numbers(evidence_text)\n            if not missing or len(slide['claims'])>=8: continue\n            for num in sorted(missing):\n                src,quote=_numeric_quote(num,web)\n                if src and quote:\n                    slide['claims'].append({'text':part,'source_id':src['id'],'evidence_quote':quote})\n                    evidence_text+=' '+quote\n                    if src['id'] not in slide['source_ids'] and len(slide['source_ids'])<8:\n                        slide['source_ids'].append(src['id'])\n"""
new2="""        # Every visible numeric value must have matching numeric evidence.\n        # This is deterministic and runs even when the model already produced many claims.\n        # Numeric evidence claims are allowed in addition to semantic claims so a slide\n        # cannot fail merely because eight semantic claims already exist.\n        evidence_text=' '.join(c.get('evidence_quote','') for c in slide['claims'])\n        preferred_ids=slide.get('source_ids', [])\n        slide_text=' '.join(_candidate_blocks(slide))\n        numeric_parts=_visible_numeric_parts(slide)\n        for part in numeric_parts:\n            missing=numbers(part)-numbers(evidence_text)\n            for num in sorted(missing):\n                src,quote=_numeric_quote(num,web,preferred_ids,slide_text)\n                if src and quote:\n                    # Reuse an existing claim with the same visible text when possible.\n                    reused=False\n                    for claim in slide['claims']:\n                        if norm(claim.get('text',''))==norm(part):\n                            claim['source_id']=src['id']; claim['evidence_quote']=quote\n                            reused=True; break\n                    if not reused:\n                        slide['claims'].append({'text':part,'source_id':src['id'],'evidence_quote':quote})\n                    evidence_text+=' '+quote\n                    if src['id'] not in slide['source_ids'] and len(slide['source_ids'])<8:\n                        slide['source_ids'].append(src['id'])\n"""
if old not in s:
    raise SystemExit('old numeric block not found')
s=s.replace(old,new2)
p.write_text(s)
