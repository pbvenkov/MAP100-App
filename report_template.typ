#set document(title: "PIN100 Analytics Report", author: "PIN100")
#set page(
  paper: "a4",
  margin: (top: 1.8cm, bottom: 1.8cm, left: 2cm, right: 2cm),
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
  size: 9.5pt,
  fill: rgb("1e293b"),
  lang: "ru"
)
#set par(justify: true, leading: 0.6em)

// ==========================================================
// СТРАНИЦА 1: ТИТУЛЬНОЕ ЗАКЛЮЧЕНИЕ
// ==========================================================

#align(left)[
  #text(size: 10pt, weight: "bold", tracking: 0.15em, fill: rgb("475569"))[PIN100 ANALYTICS]
]

#v(2.2cm)

#text(size: 22pt, weight: "bold", fill: rgb("0f172a"))[
  Аналитическое заключение: \
  Где профиль теряет первичных клиентов
]
#v(6pt)
#text(size: 11pt, weight: "medium", fill: rgb("475569"))[
  Расчет упущенной выручки локации и перетока спроса к конкурентам
]

#v(1.2cm)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 14pt,
  [
    #grid(
      columns: (auto, 1fr),
      row-gutter: 10pt,
      column-gutter: 16pt,
      [*Организация:*], [[[TITLE]]],
      [*Направление:*], [[[NICHE]]],
      [*Дата фиксации данных:*], [[[DATE]]]
    )
  ]
)

#v(1cm)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("ffffff"),
  stroke: (left: 3pt + rgb("0284c7")),
  inset: (left: 14pt, y: 11pt),
  [
    #text(weight: "bold", fill: rgb("0f172a"))[Практическая ценность для руководителя:] \
    #v(4pt)
    #text(size: 9pt, fill: rgb("475569"))[
      Отчет показывает скрытые программные фильтры Яндекс Карт, из-за которых готовые к обращению клиенты района уходят к ближайшим конкурентам. Здесь нет общих советов по рекламе: зафиксированы конкретные барьеры конверсии в профиле и рассчитан прямой кассовый разрыв бизнеса без затрат на платный трафик.
    ]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 2: РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ И ВОРОНКА ПОТЕРЬ
// ==========================================================

#text(size: 15pt, weight: "bold", fill: rgb("0f172a"))[Резюме для руководителя]

#v(8pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 12pt,
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 12pt,
    [
      #set par(justify: false)
      #text(size: 8pt, weight: "bold", fill: rgb("64748b"))[ГОТОВНОСТЬ КАРТОЧКИ К ПРИЕМУ ТРАФИКА] \
      #v(3pt)
      #text(size: 24pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]]/100] \
      #v(1pt)
      #text(size: 8pt, fill: rgb("64748b"))[Оценка факторов конверсии и ранжирования]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 12pt,
    [
      #set par(justify: false)
      #text(size: 8pt, weight: "bold", fill: rgb("64748b"))[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ] \
      #v(3pt)
      #text(size: 22pt, weight: "bold", fill: rgb("991b1b"))[[[REV_LOSS_FMT]] ₽/мес] \
      #v(1pt)
      #text(size: 8pt, fill: rgb("64748b"))[Консервативная оценка первого визита]
    ]
  )
)

#v(8pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: (left: 3pt + rgb("0284c7")),
  inset: 11pt,
  [
    #text(weight: "bold", size: 9.5pt, fill: rgb("0f172a"))[Парадокс локального поиска: почему высокого рейтинга больше недостаточно] \
    #v(3pt)
    #text(size: 8.5pt, fill: rgb("334155"))[
      Более 65% людей выбирают организацию в мобильных Картах за 40–60 секунд, не переходя на сайт (модель *Zero-Click*). Высокий рейтинг (4.8+) создает первичное доверие, но современные алгоритмы выдачи отдают верхние позиции карточкам с активным функционалом: мгновенная онлайн-запись, оцифрованный прайс и прямой чат. Карточка без этих инструментов теряет горячих клиентов еще до звонка администратору.
    ]
  ]
)

#v(8pt)

#text(size: 9.5pt, weight: "bold", fill: rgb("0f172a"))[Критический вывод анализа:] \
#v(2pt)
#text(size: 9pt, fill: rgb("334155"))[[[EXECUTIVE_SUMMARY]]]

#v(8pt)

#text(size: 10pt, weight: "bold", fill: rgb("0f172a"))[Воронка потерь: где именно карточка теряет клиентов]

#v(4pt)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 8pt,
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 0.5pt + rgb("e2e8f0"),
    inset: 9pt,
    [
      #set par(justify: false)
      #text(size: 7.5pt, weight: "bold", fill: rgb("64748b"))[1. ТРАФИК ЛИДЕРОВ РАЙОНА] \
      #v(2pt)
      #text(size: 12pt, weight: "bold", fill: rgb("0f172a"))[~[[CLIENT_LEADS]] обр./мес] \
      #v(2pt)
      #text(size: 7.5pt, fill: rgb("334155"))[Медиана прямых контактов: звонки, маршруты и онлайн-запись в ТОП-3 локации.]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 0.5pt + rgb("e2e8f0"),
    inset: 9pt,
    [
      #set par(justify: false)
      #text(size: 7.5pt, weight: "bold", fill: rgb("64748b"))[2. ЭКРАННЫЙ ФИЛЬТР] \
      #v(2pt)
      #text(size: 12pt, weight: "bold", fill: rgb("d97706"))[Отказ от звонка] \
      #v(2pt)
      #text(size: 7.5pt, fill: rgb("334155"))[65% людей не звонят, если нет онлайн-записи или не виден понятный прайс.]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 0.5pt + rgb("e2e8f0"),
    inset: 9pt,
    [
      #set par(justify: false)
      #text(size: 7.5pt, weight: "bold", fill: rgb("64748b"))[3. УХОД К СОСЕДЯМ] \
      #v(2pt)
      #text(size: 12pt, weight: "bold", fill: rgb("991b1b"))[-[[REV_LOSS_FMT]] ₽/мес] \
      #v(2pt)
      #text(size: 7.5pt, fill: rgb("334155"))[~[[LOST_LEADS]] [[TABLE_DECLENSION]] ежемесячно перетекают в активные карточки района.]
    ]
  )
)

#v(4pt)
#text(size: 7.5pt, fill: rgb("64748b"))[
  \* Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом повторных визитов и прикрепления пациентов годовой отток районного бюджета составляет до [[LTV_LOSS_FMT]] ₽.
]

#v(6pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 8pt,
  [
    #text(size: 8pt, fill: rgb("475569"))[
      *Важное примечание:* Оценка [[SCORE]] / 100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
    ]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 3: ТОП-3 ПРИЧИНЫ ПОТЕРИ КЛИЕНТОВ
// ==========================================================

#text(size: 15pt, weight: "bold", fill: rgb("0f172a"))[[[PAGE_3_HEADING]]]

#v(3pt)
#text(size: 9.5pt, fill: rgb("475569"))[[[PAGE_3_SUBTITLE]]]

#v(10pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 12pt,
  [
    #text(size: 10.5pt, weight: "bold", fill: rgb("0f172a"))[1. [[FAIL_1_TITLE]]] \
    #v(4pt)
    #text(size: 9pt, fill: rgb("334155"))[[[FAIL_1_DESC]]]
  ]
)

#v(8pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 12pt,
  [
    #text(size: 10.5pt, weight: "bold", fill: rgb("0f172a"))[2. [[FAIL_2_TITLE]]] \
    #v(4pt)
    #text(size: 9pt, fill: rgb("334155"))[[[FAIL_2_DESC]]]
  ]
)

#v(8pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: 12pt,
  [
    #text(size: 10.5pt, weight: "bold", fill: rgb("0f172a"))[3. [[FAIL_3_TITLE]]] \
    #v(4pt)
    #text(size: 9pt, fill: rgb("334155"))[[[FAIL_3_DESC]]]
  ]
)

#pagebreak()

// ==========================================================
// СТРАНИЦА 4: ПЛАН УСТРАНЕНИЯ РАЗРЫВА И CTA
// ==========================================================

#text(size: 15pt, weight: "bold", fill: rgb("0f172a"))[План устранения кассового разрыва]

#v(3pt)
#text(size: 9pt, fill: rgb("475569"))[Пошаговый план возврата районного потока обращений в кассу организации:]

#v(8pt)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 8pt,
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 8pt,
    [
      #set par(justify: false, leading: 0.5em)
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 1: СТАРТ] \
      #v(1pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[3-5 дней] \
      #v(4pt)
      #text(size: 8pt, fill: rgb("334155"))[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 8pt,
    [
      #set par(justify: false, leading: 0.5em)
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 2: ОЦИФРОВКА] \
      #v(1pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[14 дней] \
      #v(4pt)
      #text(size: 8pt, fill: rgb("334155"))[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
    ]
  ),
  rect(
    width: 100%,
    radius: 6pt,
    fill: rgb("f8fafc"),
    stroke: 1pt + rgb("e2e8f0"),
    inset: 8pt,
    [
      #set par(justify: false, leading: 0.5em)
      #text(size: 8.5pt, weight: "bold", fill: rgb("0f172a"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ] \
      #v(1pt)
      #text(size: 8pt, weight: "bold", fill: rgb("0284c7"))[Постоянно] \
      #v(4pt)
      #text(size: 8pt, fill: rgb("334155"))[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
    ]
  )
)

#v(8pt)

#text(size: 9pt)[
  *Цена недели бездействия:* Каждая неделя промедления с исправлением технических недочетов обходится организации примерно в *[[WEEKLY_LOSS_FMT]] ₽*, которые безвозвратно переходят к вашим прямым конкурентам.
]

#v(4pt)

#text(size: 9pt)[
  *Экономика окупаемости:* При текущих потерях порядка *[[REV_LOSS_FMT]] ₽/мес*, привлечение даже 4-6 дополнительных первичных клиентов полностью окупает любые сервисные расходы на настройку уже в первые 30 дней.
]

#v(8pt)

#rect(
  width: 100%,
  radius: 6pt,
  fill: rgb("f8fafc"),
  stroke: 1pt + rgb("e2e8f0"),
  inset: (x: 12pt, y: 9pt),
  [
    #grid(
      columns: (1fr, auto),
      gutter: 10pt,
      align: (left + horizon, right + horizon),
      [
        #text(size: 9.5pt, weight: "bold", fill: rgb("0f172a"))[Персональный видеоразбор профиля] \
        #v(2pt)
        #text(size: 8.5pt, fill: rgb("334155"))[
          Напишите в Telegram — пришлем 3-минутное видео по вашей карточке с разбором конкретных точек утечки пациентов и ответим на вопросы руководителя.
        ]
      ],
      [
        #text(size: 9.5pt, weight: "bold", fill: rgb("0284c7"))[
          Telegram: #link("https://t.me/paulvenkov")[\@paulvenkov]
        ]
      ]
    )
    #v(4pt)
    #line(length: 100%, stroke: 0.5pt + rgb("e2e8f0"))
    #v(2pt)
    #text(size: 7.5pt, fill: rgb("64748b"))[
      \* По запросу также подготовим комплект готовых материалов для администратора (шаблон прейскуранта для импорта в 1 клик, продающее описание и регламент связки МИС с онлайн-записью).
    ]
  ]
)
