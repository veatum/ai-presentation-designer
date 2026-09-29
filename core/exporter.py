from __future__ import annotations
import html,shutil,subprocess,tempfile
from pathlib import Path
from pptx import Presentation
from .renderer import all_shapes


def export_pdfs_batch(pptx_paths,out_dir,timeout=120):
    """Convert a set of PPTX files to PDF, falling back per file when LO rejects one.
    The batch path is fast; a single bad master/export cannot cancel the other results.
    """
    binary=shutil.which('soffice') or shutil.which('libreoffice')
    if not binary: raise ValueError('Для PDF установите LibreOffice.')
    paths=[Path(p) for p in pptx_paths]
    if not paths: return {}
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    result={}
    try:
        with tempfile.TemporaryDirectory() as profile:
            cmd=[binary,'-env:UserInstallation='+Path(profile).as_uri(),'--headless','--convert-to','pdf','--outdir',str(out_dir)]
            cmd.extend(str(p) for p in paths)
            subprocess.run(cmd,check=True,capture_output=True,timeout=timeout)
        result={p.stem:out_dir/(p.stem+'.pdf') for p in paths if (out_dir/(p.stem+'.pdf')).exists()}
    except Exception:
        result={}
    missing=[p for p in paths if p.stem not in result]
    # Give each failed file one isolated attempt. Keep all successful siblings.
    per_file=max(8,min(25,max(8,int(timeout/max(1,len(missing))))))
    for p in missing:
        try:
            out=export_pdf(p,out_dir,timeout=per_file)
            result[p.stem]=out
        except Exception:
            continue
    return result


def export_pdf(pptx_path,out_dir,timeout=60):
    binary=shutil.which('soffice') or shutil.which('libreoffice')
    if not binary: raise ValueError('Для PDF установите LibreOffice.')
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([binary,'-env:UserInstallation='+Path(profile).as_uri(),'--headless','--convert-to','pdf','--outdir',str(out_dir),str(pptx_path)],check=True,capture_output=True,timeout=timeout)
    out=out_dir/(Path(pptx_path).stem+'.pdf')
    if not out.exists(): raise ValueError('Конвертер не создал PDF.')
    return out

def export_preview_png(pdf_path,out_path):
    import fitz
    with fitz.open(str(pdf_path)) as doc:
        doc[0].get_pixmap(matrix=fitz.Matrix(1.2,1.2),alpha=False).save(str(out_path))
    return Path(out_path)

def export_html(pptx_path,out_path,pdf_path=None):
    chunks=['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Презентация</title><style>body{background:#e9edf3;font:18px Arial;margin:0}section{background:white;margin:24px auto;max-width:1200px;padding:24px}svg{width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:10px}a{color:#2463eb}@media print{section{break-after:page;margin:0}}</style>']
    if pdf_path:
        import fitz
        with fitz.open(str(pdf_path)) as doc:
            for page in doc:
                svg=page.get_svg_image(text_as_path=False)
                # PDFs render the same exported PPTX, including charts and template graphics.
                chunks.append('<section>'+svg)
                links=list(dict.fromkeys(l.get('uri') for l in page.get_links() if (l.get('uri') or '').startswith(('http://','https://'))))
                chunks.extend('<p><a href="'+html.escape(u,quote=True)+'">'+html.escape(u)+'</a></p>' for u in links)
                chunks.append('</section>')
    else:
        chunks.append('<p>Текстовая версия: LibreOffice недоступен, оформление шаблона не отображается.</p>')
        for slide in Presentation(str(pptx_path)).slides:
            chunks.append('<section>')
            for s in all_shapes(slide.shapes):
                if s.has_text_frame:
                    for p in s.text_frame.paragraphs:
                        chunks.append('<p>'+''.join(('<a href="'+html.escape(r.hyperlink.address,quote=True)+'">'+html.escape(r.text)+'</a>') if r.hyperlink.address and r.hyperlink.address.startswith(('https://','http://')) else html.escape(r.text) for r in p.runs)+'</p>')
                if s.has_table:
                    chunks.append('<table>'+''.join('<tr>'+''.join('<td>'+html.escape(c.text)+'</td>' for c in row.cells)+'</tr>' for row in s.table.rows)+'</table>')
                if s.has_chart:
                    categories=[c.label for c in s.chart.plots[0].categories]
                    for series in s.chart.series:
                        chunks.append('<h3>'+html.escape(series.name)+'</h3><table>'+''.join('<tr><td>'+html.escape(str(k))+'</td><td>'+html.escape(str(v))+'</td></tr>' for k,v in zip(categories,series.values))+'</table>')
            chunks.append('</section>')
    chunks.append('</html>');Path(out_path).write_text('\n'.join(chunks),encoding='utf-8');return Path(out_path)
