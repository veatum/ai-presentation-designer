(() => {
  const isDemo = location.hostname.endsWith('.github.io') ||
    new URLSearchParams(location.search).get('demo') === '1';
  if (!isDemo) return;

  document.title = 'AI Presentation Designer — демо';
  document.querySelector('.badge').textContent = 'Демонстрационная версия';
  const notice = document.createElement('section');
  notice.className = 'card';
  notice.style.marginBottom = '18px';
  notice.innerHTML = `
    <h2 style="margin-top:0">Посмотрите интерфейс и готовые презентации</h2>
    <p class="sub">Это демо на GitHub Pages. Создание новых презентаций,
      исследование источников и исправление слайдов доступны при запуске
      полной версии с сервером. Здесь можно скачать три готовых примера.</p>
    <div class="links">
      <a href="#demo-examples">Готовые примеры</a>
      <a href="https://github.com/veatum/ai-presentation-designer#5-локальный-запуск-без-docker--основной-путь-для-windowsmacos">Как запустить полную версию</a>
    </div>`;
  document.querySelector('.hero').before(notice);
  document.querySelector('.hero .sub').textContent =
    'Так выглядит полная версия: запрос, материалы и шаблон превращаются в редактируемую презентацию. В демо поля недоступны, файлы не отправляются.';
  document.querySelectorAll('.hero input, .hero textarea, .hero select').forEach(input => {
    input.disabled = true;
  });
  const generateButton = document.getElementById('generate');
  generateButton.textContent = 'Посмотреть готовые примеры';
  generateButton.onclick = () => {
    document.getElementById('demo-examples').scrollIntoView({behavior: 'smooth'});
  };
  document.getElementById('status').textContent = 'Генерация доступна в полной версии';

  const examples = [
    ['balanced', 'Сбалансированная', 'Текст и визуальные элементы в общей композиции.'],
    ['columns', 'Колонки', 'То же содержание в компоновке по колонкам.'],
    ['editorial', 'Редакционная', 'Альтернативная композиция той же презентации.'],
  ];
  document.getElementById('results').innerHTML = `
    <section class="card" id="demo-examples" style="scroll-margin-top:20px">
      <h2 style="margin-top:0">Одна презентация — три варианта оформления</h2>
      <p class="sub">Готовые примеры из проекта: по 10 слайдов в каждом.
        Это заранее созданные файлы, а не результат нового запроса.</p>
      <div class="grid">${examples.map(([variant, title, description]) => `
        <article class="card variant">
          <h3>${title}</h3>
          <p class="small">${description}</p>
          <div class="links"><a href="../examples/showcase/presentation_${variant}.pptx" download>Скачать PPTX</a></div>
        </article>`).join('')}
      </div>
    </section>`;
})();
