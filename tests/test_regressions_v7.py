
import json, sys, types
from pathlib import Path
from pptx import Presentation

# Minimal stub only if openai isn't installed in the test environment.
try:
    import openai  # noqa: F401
except Exception:
    m=types.ModuleType("openai")
    class Base(Exception): pass
    for name in ["APIStatusError","APIConnectionError","APITimeoutError","RateLimitError","InternalServerError"]:
        setattr(m,name,type(name,(Base,),{}))
    class OpenAI: pass
    m.OpenAI=OpenAI
    sys.modules["openai"]=m

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from core.web_research import _looks_like_search_ui, public_url
from core.renderer import render_variant, VARIANTS
from core.template_parser import parse_template
from core.template_profiles import builtin_template_path
from core.quality import harden_plan

SOURCE = [{
    "id":"W1","kind":"web","verified":True,"title":"Verified source",
    "url":"https://example.org/article","text":(
        "Сервис использует структурированный вывод для надёжного обмена данными между моделью и приложением. "
        "Проверка источников позволяет отделять факты от интерпретаций. "
        "Сравнение трёх вариантов помогает выбрать композицию без изменения содержания. "
        "В 2024 году в примере использовано 20 случаев и подготовлено 10 вариантов."
    )*8
}]

B1="Структурированный вывод помогает приложению получить предсказуемую структуру данных, которую можно проверить до рендера и безопасно передать следующему программному слою без ручной правки."
B2="Разделение содержания и оформления позволяет переносить один смысловой материал на разные шаблоны, сохраняя факты и меняя только композицию, плотность и визуальные паттерны."
B3="Проверка источников отделяет подтверждённые сведения от интерпретаций, поэтому итоговый слайд может объяснять механизм и следствие, не подменяя доказательство одной ссылкой."
B4="Финальный аудит проверяет не только наличие файла, но и редактируемость объектов, границы элементов, читаемость текста и соответствие выбранному шаблону."

def _plan():
    slides=[]
    for n in range(1,11):
        base={"number":n,"kind":"content","title":f"Смысловой слайд {n}","subtitle":"",
              "points":[B1,B2],"left_title":"","left_points":[],"right_title":"","right_points":[],
              "metrics":[],"table":None,"chart":None,"quote":"","timeline":[],"notes":"",
              "source_ids":["W1"],"claims":[]}
        if n==1:
            base["kind"]="title"; base["title"]="Надёжная генерация презентаций"; base["points"]=[]
        elif n==3:
            base["kind"]="two_column"; base["points"]=[]; base["left_title"]="Содержание"; base["left_points"]=[B1,B2]; base["right_title"]="Оформление"; base["right_points"]=[B3,B4]
        elif n==4:
            base["kind"]="process"; base["points"]=[]; base["timeline"]=[
                {"label":"Источники","detail":B1},{"label":"Проверка","detail":B3},{"label":"Рендер","detail":B4}]
        elif n==5:
            base["kind"]="metrics"; base["points"]=[B3,B4]
            base["metrics"]=[{"label":"Примеры","value":"20","note":B1},{"label":"Варианты","value":"10","note":B2}]
        elif n==8:
            base["kind"]="table"; base["points"]=[B1,B2]
            base["table"]={"columns":["Этап","Описание"],"rows":[["Поиск",B1],["Проверка",B3],["Рендер",B4]]}
        elif n==9:
            base["kind"]="chart"; base["points"]=[B3,B4]
            base["chart"]={"type":"column","labels":["2024","20","10"],"values":[2024,20,10],"unit":"Значение"}
        elif n==10:
            base["kind"]="summary"
        slides.append(base)
    return {"title":"Надёжная генерация","subtitle":"Источники → содержание → рендер",
            "audience":"Эксперт","purpose":"Тест", "slides":slides}

def test_search_ui_rejected():
    bad="Справка - Google Поиск Войти Справочный центр Попробуйте следующее Отправить отзыв"
    assert _looks_like_search_ui(bad,"Справка - Google Поиск")
    try:
        public_url("https://www.google.com/search?q=test")
    except ValueError:
        pass
    else:
        raise AssertionError("Search engine URL must not be accepted")

def test_harden_removes_search_artifacts():
    plan=_plan()
    plan["slides"][1]["points"][0]="Факт о сервисе. Справка - Google Поиск Войти"
    hardened=harden_plan(plan,SOURCE)
    assert "Google Поиск" not in hardened["slides"][1]["points"][0]
    assert "Войти" not in hardened["slides"][1]["points"][0]

def test_all_vk_variants_render_with_dense_table(tmp_path):
    plan=_plan()
    out=tmp_path / "v7_regression_render"; out.mkdir(parents=True,exist_ok=True)
    for tid in ("vk_tech","vk_workspace","vk_education"):
        tpl=builtin_template_path(tid); spec=parse_template(tpl)
        for variant in VARIANTS:
            dst=out/f"{tid}_{variant}.pptx"
            render_variant(tpl,plan,spec,dst,variant,tid,SOURCE)
            assert len(Presentation(str(dst)).slides)==10
