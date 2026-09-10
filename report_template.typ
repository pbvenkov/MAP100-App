#set document(title: "PIN100 Analytics Report", author: "PIN100")
#set page(
  paper: "a4",
  margin: (top: 2.2cm, bottom: 2.2cm, left: 2.2cm, right: 2.2cm),
  footer: [
    #set text(size: 8pt, fill: rgb("64748b"))
    #grid(
      columns: (1fr, auto),
      align: (left, right),
      [PIN100 Analytics | Независимый аудит поисковой гео-выдачи],
      [Стр. #context counter(page).display("1")]
    )
  ]
)

#set text(
  font: ("Liberation Sans", "DejaVu Sans", "Arial", "Roboto"),
  size: 10pt,
  fill: rgb("1e293b"),
  lang: "ru"
)
#set par(justify: true, leading: 0.65em)

// ==========================================================
// СТРАНИЦА 1: ТИТУЛЬНОЕ ЗАКЛЮЧЕНИЕ
// ==========================================================

#align(left)[
  #text(size: 10pt, weight: "bold", tracking: 0.15em, fill: rgb("475569"))[PIN100 ANALYTICS]
]

#v(2.5cm)

#text(size: 24pt, weight: "bold", fill: rgb("0f172a"))[
  Аналитическое Заключение: \
  Оцифровка потерь первичного потока
]

#v(1.5cm)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 16pt,
  [
    #grid(
      columns: (auto, 1fr),
      row-gutter: 12pt,
      column-gutter: 16pt,
      [*Организация:*], [[[TITLE]]],
      [*Направление:*], [[[NICHE]]],
      [*Дата фиксации данных:*], [[[DATE]]]
    )
  ]
)

#v(1.2cm)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("ffffff"),
  stroke: (left: 3pt + rgb("0284c7")),
  inset: (left: 14pt, y: 10pt),
  [
    #text(weight: "bold", fill: rgb("0f172a"))[Методология аудита:] \
    #v(4pt)
    #text(size: 9pt, fill: rgb("475569"))[
      Оценка готовности профиля к приему первичных обращений по параметрам поисковой доступности, полноты прейскуранта и простоты записи. Анализ учитывает отраслевые стандарты размещения информации об услугах и квалификации специалистов.
    ]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 2: РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ И РАСЧЕТ ПОТЕРЬ
// ==========================================================

#text(size: 16pt, weight: "bold", fill: rgb("0f172a"))[Резюме для руководителя]

#v(10pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 14pt,
    [
      #text(size: 8.5pt, weight: "bold", fill: rgb("64748b"))[ВИДИМОСТЬ КАРТОЧКИ В ПОИСКЕ] \
      #v(4pt)
      #text(size: 26pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]]/100] \
      #v(2pt)
      #text(size: 8pt, fill: rgb("64748b"))[Оценка по ключевым факторам ранжирования]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 14pt,
    [
      #text(size: 8.5pt, weight: "bold", fill: rgb("64748b"))[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ] \
      #v(4pt)
      #text(size: 24pt, weight: "bold", fill: rgb("991b1b"))[[[REV_LOSS_FMT]] ₽/мес] \
      #v(2pt)
      #text(size: 8pt, fill: rgb("64748b"))[Консервативная оценка первого визита]
    ]
  )
)

#v(12pt)

#text(size: 10pt, weight: "bold", fill: rgb("0f172a"))[Критический вывод анализа:] \
#v(3pt)
#text(size: 9.5pt, fill: rgb("334155"))[[[EXECUTIVE_SUMMARY]]]

#v(14pt)

#text(size: 10pt, weight: "bold", fill: rgb("0f172a"))[Прозрачный расчет потерь (экономика первичного приема):]

#v(4pt)

#table(
  columns: (2.2fr, 1.2fr, 2.6fr),
  inset: (x: 9pt, y: 7.5pt),
  stroke: 0.5pt + rgb("e2e8f0"),
  fill: (x, y) => if y == 0 { rgb("f8fafc") } else { none },
  [*Параметр расчета*], [*Значение*], [*Как считаем*],
  [Пул спроса лидеров района], [[[CLIENT_LEADS]] обр./мес], [Поток обращений в ТОП-3 клиники локации],
  [Дефицит видимости профиля], [[[DEV]]%], [100% минус текущий балл ([[SCORE]])],
  [Клиенты, ушедшие к конкурентам], [[[LOST_LEADS]] [[TABLE_DECLENSION]]], [Спрос лидеров × Дефицит видимости],
  [Базовый чек первого визита], [[[CLIENT_CHECK_FMT]] ₽], [Консервативный порог первого визита],
  [Прямые потери в месяц], [*[[REV_LOSS_FMT]] ₽/мес*], [Недополученная выручка первого визита]
)

#v(2pt)
#text(size: 7.5pt, fill: rgb("64748b"))[
  \* Расчет выполнен строго по первому чеку. С учетом повторных визитов и прикрепления клиентов ([[CLIENT_LTV]] мес.) совокупный отток выручки в пользу прямых конкурентов района составляет до [[LTV_LOSS_FMT]] ₽ в год.
]

#v(10pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 10pt,
  [
    #text(size: 8pt, fill: rgb("475569"))[
      *Важное примечание:* Оценка [[SCORE]] / 100 фиксирует исключительно техническую видимость профиля в поиске Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]]. Это программные особенности поисковой выдачи, которые не зависят от работы администраторов.
    ]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 3: ТОП-3 ПРИЧИНЫ ПОТЕРИ КЛИЕНТОВ
// ==========================================================

#text(size: 16pt, weight: "bold", fill: rgb("0f172a"))[[[PAGE_3_HEADING]]]

#v(4pt)
#text(size: 9.5pt, fill: rgb("475569"))[[[PAGE_3_SUBTITLE]]]

#v(14pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 14pt,
  [
    #text(size: 11pt, weight: "bold", fill: rgb("0f172a"))[1. [[FAIL_1_TITLE]]] \
    #v(6pt)
    #text(size: 9.5pt, fill: rgb("334155"))[[[FAIL_1_DESC]]]
  ]
)

#v(10pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 14pt,
  [
    #text(size: 11pt, weight: "bold", fill: rgb("0f172a"))[2. [[FAIL_2_TITLE]]] \
    #v(6pt)
    #text(size: 9.5pt, fill: rgb("334155"))[[[FAIL_2_DESC]]]
  ]
)

#v(10pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 14pt,
  [
    #text(size: 11pt, weight: "bold", fill: rgb("0f172a"))[3. [[FAIL_3_TITLE]]] \
    #v(6pt)
    #text(size: 9.5pt, fill: rgb("334155"))[[[FAIL_3_DESC]]]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 4: ПЛАН УСТРАНЕНИЯ РАЗРЫВА И CTA
// ==========================================================

#text(size: 16pt, weight: "bold", fill: rgb("0f172a"))[План устранения кассового разрыва]

#v(4pt)
#text(size: 9.5pt, fill: rgb("475569"))[Пошаговый план возврата районного потока обращений в кассу организации:]

#v(14pt)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 10pt,
  rect(
    width: 100%,
    height: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 10pt,
    [
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 1: БЫСТРЫЙ СТАРТ] \
      #v(2pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[3-5 дней] \
      #v(6pt)
      #text(size: 8.5pt, fill: rgb("334155"))[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
    ]
  ),
  rect(
    width: 100%,
    height: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 10pt,
    [
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 2: ПОЛНАЯ ОЦИФРОВКА] \
      #v(2pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[14 дней] \
      #v(6pt)
      #text(size: 8.5pt, fill: rgb("334155"))[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
    ]
  ),
  rect(
    width: 100%,
    height: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 10pt,
    [
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ] \
      #v(2pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[Постоянно] \
      #v(6pt)
      #text(size: 8.5pt, fill: rgb("334155"))[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
    ]
  )
)

#v(14pt)

#text(size: 9.5pt)[
  *Цена недели бездействия:* Каждая неделя промедления с исправлением технических недочетов обходится организации примерно в *[[WEEKLY_LOSS_FMT]] ₽*, которые безвозвратно переходят к вашим прямым конкурентам.
]

#v(6pt)

#text(size: 9.5pt)[
  *Экономика окупаемости:* При текущих потерях порядка *[[REV_LOSS_FMT]] ₽/мес*, привлечение даже 4-6 дополнительных первичных клиентов полностью окупает любые сервисные расходы на настройку уже в первые 30 дней.
]

#v(16pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f1f5f9"),
  stroke: 1pt + rgb("cbd5e1"),
  inset: 14pt,
  [
    #text(size: 11pt, weight: "bold", fill: rgb("0f172a"))[Получить пошаговый план исправления (ТЗ)] \
    #v(4pt)
    #text(size: 9.5pt, fill: rgb("334155"))[
      Напишите в Telegram — пришлем короткое 3-минутное персональное видео по вашей карточке с разбором скрытых технических ошибок профиля.
    ] \
    #v(6pt)
    #text(size: 10pt, weight: "bold", fill: rgb("0284c7"))[Telegram: \@paulvenkov]
  ]
)
