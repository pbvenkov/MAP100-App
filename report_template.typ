#set document(title: "Аналитическое Заключение - [[TITLE]]", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 18mm),
  numbering: "1",
  footer: context [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Независимый аудит поисковой гео-выдачи
    #h(1fr)
    Стр. #counter(page).display()
  ]
)

#set text(font: ("Inter", "Arial", "sans-serif"), size: 9.5pt, fill: rgb("334155"), lang: "ru")
#set par(leading: 0.55em)
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// ==========================================
// СТР. 1: ОБЛОЖКА И МЕТОДОЛОГИЯ
// ==========================================
#v(85pt)
#text(size: 12pt, fill: rgb("8B7355"), weight: "bold")[PIN100 ANALYTICS]
#v(8pt)
#text(size: 24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитическое Заключение:\ Оцифровка потерь первичного потока]
#v(10pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(25pt)
#text(size: 11pt, fill: rgb("475569"))[
  Организация: *[[TITLE]]* \
  Направление: *[[NICHE]]* \
  Дата фиксации данных: *[[DATE]]*
]
#v(35pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(size: 8.5pt, fill: rgb("64748B"))[
    *Методология аудита:* Оценка готовности профиля к приему первичных обращений по параметрам поисковой доступности, полноты прейскуранта и простоты записи. Анализ учитывает отраслевые стандарты размещения информации об услугах и квалификации специалистов.
  ]
]

#pagebreak()

// ==========================================
// СТР. 2: РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ
// ==========================================
#heading(level: 2)[Резюме для руководителя]
#v(4pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 12pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
      #text(size: 8pt, fill: rgb("64748B"), weight: "bold")[ВИДИМОСТЬ КАРТОЧКИ В ПОИСКЕ] \
      #v(3pt)
      #text(size: 21pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]] / 100]
      #v(2pt)
      #text(size: 8pt, fill: rgb("94A3B8"), style: "italic")[Оценка по ключевым факторам ранжирования]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
      #text(size: 8pt, fill: rgb("64748B"), weight: "bold")[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ] \
      #v(3pt)
      #text(size: 19pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]
      #v(2pt)
      #text(size: 8pt, fill: rgb("94A3B8"), style: "italic")[Консервативная оценка первого визита]
    ]
  ]
)

#v(4pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
  #text(size: 9.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод анализа:]
  #v(2pt)
  #text(size: 8.5pt, fill: rgb("334155"))[
    [[EXECUTIVE_SUMMARY]]
  ]
]

#v(4pt)
#text(size: 9pt, weight: "bold", fill: rgb("0A1128"))[Прозрачный расчет потерь (юнит-экономика локации):]
#v(2pt)

#set table.cell(inset: 5.5pt)
#table(
  columns: (1.3fr, 1fr, 1.4fr),
  stroke: 0.5pt + rgb("E2E8F0"),
  fill: (x, y) => if y == 0 { rgb("F1F5F9") } else if y == 5 { rgb("FFF1F2") } else { none },
  align: (left + horizon, center + horizon, left + horizon),
  [#text(size: 8pt, weight: "bold")[Параметр расчета]], [#text(size: 8pt, weight: "bold")[Значение]], [#text(size: 8pt, weight: "bold")[Как считаем]],
  [#text(size: 8.5pt)[Пул спроса лидеров района]], [#text(size: 8.5pt)[~[[CLIENT_LEADS]] обр./мес]], [#text(size: 8pt, fill: rgb("64748B"))[Поток обращений в ТОП-3 клиники локации]],
  [#text(size: 8.5pt)[Дефицит видимости профиля]], [#text(size: 8.5pt)[[[DEV]]%]], [#text(size: 8pt, fill: rgb("64748B"))[100% минус текущий балл ([[SCORE]])]],
  [#text(size: 8.5pt)[Клиенты, ушедшие к конкурентам]], [#text(size: 8.5pt)[~[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]]], [#text(size: 8pt, fill: rgb("64748B"))[Спрос лидеров × Дефицит видимости]],
  [#text(size: 8.5pt)[Базовый чек первого визита]], [#text(size: 8.5pt)[[[CLIENT_CHECK_FMT]]~₽]], [#text(size: 8pt, fill: rgb("64748B"))[Консервативный порог первого визита]],
  [#text(size: 8.5pt, weight: "bold", fill: rgb("9F1239"))[Прямые потери в месяц]], [#text(size: 8.5pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]], [#text(size: 8pt, weight: "bold", fill: rgb("9F1239"))[Недополученная выручка первого визита]]
)

#v(2pt)
#text(size: 7.5pt, fill: rgb("64748B"), style: "italic")[
  \* Расчет выполнен строго по первому чеку. С учетом повторных визитов и прикрепления клиентов ([[CLIENT_LTV]]~мес.) совокупный отток выручки в пользу прямых конкурентов района составляет до *[[LTV_LOSS_FMT]]~₽ в год*.
]

#v(4pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 3pt, inset: 7pt)[
  #text(size: 8pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка *[[SCORE]] / 100* фиксирует исключительно техническую видимость профиля в поиске Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]]. Это программные особенности поисковой выдачи, которые не зависят от работы администраторов.
  ]
]

#pagebreak()

// ==========================================
// СТР. 3: ТОЧКИ РОСТА И ПРИЧИНЫ ПОТЕРЬ (СТРОГО ДИНАМИЧЕСКИЕ)
// ==========================================
#heading(level: 2)[[[PAGE_3_HEADING]]]
#v(4pt)
#text(size: 9pt, fill: rgb("475569"))[[[PAGE_3_SUBTITLE]]]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. [[FAIL_1_TITLE]]]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[[[FAIL_1_DESC]]]
]
#v(6pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. [[FAIL_2_TITLE]]]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[[[FAIL_2_DESC]]]
]
#v(6pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. [[FAIL_3_TITLE]]]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[[[FAIL_3_DESC]]]
]

#pagebreak()

// ==========================================
// СТР. 4: ПЛАН ДЕЙСТВИЙ И СЛЕДУЮЩИЙ ШАГ
// ==========================================
#heading(level: 2)[План устранения кассового разрыва]
#v(4pt)
#text(size: 9pt, fill: rgb("475569"))[Пошаговый план возврата районного потока обращений в кассу организации:]
#v(7pt)

#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(size: 7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 1: БЫСТРЫЙ СТАРТ] \
      #v(2pt)
      #text(size: 10.5pt, weight: "bold", fill: rgb("0A1128"))[3–5 дней] \
      #v(3pt)
      #text(size: 7.5pt, fill: rgb("475569"))[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 8pt)[
      #text(size: 7.5pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 2: ПОЛНАЯ ОЦИФРОВКА] \
      #v(2pt)
      #text(size: 11.5pt, weight: "bold", fill: rgb("8B7355"))[14 дней] \
      #v(3pt)
      #text(size: 7.5pt, fill: rgb("0A1128"), weight: "bold")[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(size: 7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ] \
      #v(2pt)
      #text(size: 10.5pt, weight: "bold", fill: rgb("0A1128"))[Постоянно] \
      #v(3pt)
      #text(size: 7.5pt, fill: rgb("475569"))[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
    ]
  ]
)

#v(7pt)
#rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 4pt, inset: 8.5pt)[
  #text(size: 8.5pt, fill: rgb("9F1239"))[
    *Цена бездействия (Cost of Inaction):* Каждая неделя промедления с исправлением технических недочетов обходится организации примерно в *[[WEEKLY_LOSS_FMT]]~₽*, которые безвозвратно переходят к вашим прямым конкурентам.
  ]
]

#v(5pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8.5pt)[
  #text(size: 8pt, fill: rgb("334155"))[
    *Экономика окупаемости:* При текущих потерях порядка *[[REV_LOSS_FMT]]~₽/мес*, привлечение даже 4–6 дополнительных первичных клиентов полностью окупает любые сервисные расходы на настройку уже в первые 30 дней.
  ]
]

#v(7pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 11pt)[
  #grid(
    columns: (2.3fr, 1fr),
    gutter: 10pt,
    align: (left + horizon, center + horizon),
    [
      #text(size: 9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Получить пошаговый план исправления (ТЗ)] \
      #v(2pt)
      #text(size: 8pt, fill: rgb("CBD5E1"))[Напишите в Telegram — пришлем короткое 3-минутное персональное видео по вашей карточке с разбором скрытых технических ошибок профиля.]
    ],
    [
      #rect(fill: rgb("1E293B"), stroke: 0.5pt + rgb("8B7355"), radius: 3pt, inset: 7pt)[
        #text(size: 8pt, weight: "bold", fill: rgb("F1F5F9"))[Telegram:\ #text(fill: rgb("D97706"))[\@paulvenkov]]
      ]
    ]
  )
]
