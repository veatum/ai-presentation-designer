# DESIGN_HANDOFF_TO_SHEIKH.md

## Главное

Шейхмагомед отвечает за реализацию продукта. Саидская часть — дать ему формализованные правила визуальной структуры, а затем принимать результат.

## 1. Источники

- VK Education: 55 слайдов, 13.333×7.5 in.
- VK Tech: 54 слайда, 10×5.625 in.
- VK WorkSpace: 29 слайдов, 13.333×7.5 in.

## 2. Реализовать parser

Извлекать: slide size, slide layout name, shape type, x/y/w/h, text, font family/size/color, fill/stroke, image dimensions/aspect ratio, table/chart objects, groups, footer/logo.

## 3. Layout registry

Использовать `data/layout_registry.json` как стартовый семантический registry, а `data/template_catalog.json` — как полный технический снимок.

Ключ: `content role → compatible layout → slots → fit check → render`.

Не создавать новые свободные text boxes, когда в шаблоне есть подходящие slots.

## 4. Overflow policy

Сначала: сокращение текста → переформулировка → удаление второстепенного → другой layout → только затем мягкая типографическая адаптация.

## 5. Three variants

Варианты могут отличаться плотностью/макетом/способом визуализации, но не должны нарушать правила конкретного шаблона.

## 6. Jury deck

Не путать с входными шаблонами. `ЛЦТ2026 Шаблон презентации.pptx` — отдельная deck для жюри. Слайд 7 и 8–11 организаторы пометили обязательными; для решения рекомендуются layouts 12–29.

## 7. Definition of done для визуальной части

- parser не привязан к именам файлов;
- layout выбирается по структуре/семантике;
- нет overlap/overflow;
- изображения не растягиваются;
- typography/palette соответствуют template;
- 3 variants различимы;
- PPTX остаётся редактируемым.
