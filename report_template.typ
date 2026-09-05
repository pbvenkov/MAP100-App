#set document(title: "Аналитическое Заключение - [[TITLE]]", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 22mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Строго конфиденциально
    #h(1fr)
    #context [Стр. #counter(page).display("1")]
  ]
)

#set text(font: ("Inter", "Arial", "sans-serif"), size: 10pt, fill: rgb("334155"), lang: "ru")
#set par(leading: 0.58em)
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// ==========================================
// СТР. 1 ОБЛОЖКА
// ==========================================
#v(110pt)
#text(12pt, fill: rgb("8B7355"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(10pt)
#text(26pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитическое Заключение:\ Оцифровка потерь первичного потока]
#v(12pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(35pt)
#text(11pt, fill: rgb("475569"))[
  Организация: #strong[[[TITLE]]] \
  Направление: #strong[[[NICHE]]] \
  Дата фиксации данных: #strong[[[DATE]]]
]

#pagebreak()

// ==========================================
// СТР. 2 EXECUTIVE SUMMARY (РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ)
// ==========================================
#heading(level: 2)[Резюме для руководителя]
#v(8pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 12pt)[
      #text(8pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ВИДИМОСТЬ КАРТОЧКИ В ПОИСКЕ]
      \
      #v(5pt)
      #text(23pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]] / 100]
      #v(2pt)
      #text(8pt, fill: rgb("94A3B8"), style: "italic")[Оценка готовности профиля для клиентов]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 12pt)[
      #text(8pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]
      \
      #v(5pt)
      #text(21pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]
      #v(2pt)
      #text(8pt, fill: rgb("94A3B8"), style: "italic")[Консервативная оценка первого визита]
    ]
  ]
)

#v(8pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод анализа:]
  #v(4pt)
  #text(9pt, fill: rgb("334155"))[Прямо сейчас профиль скрыт от *[[DEV]]% целевых клиентов* вашего района. Из-за технических недочетов в оформлении карточки вы каждый месяц отдаете конкурентам около *[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]*.]
]

#v(8pt)
#text(9.5pt, weight: "bold", fill: rgb("0A1128"))[Прозрачный расчет потерь (юнит-экономика):]
#v(3pt)

#table(
  columns: (1.3fr, 1fr, 1.4fr),
  stroke: 0.5pt + rgb("E2E8F0"),
  fill: (col, row) => if row == 0 { rgb("F1F5F9") } else if row == 5 { rgb("FFF1F2") } else { none },
  inset: 6pt,
  align: (left + horizon, center + horizon, left + horizon),
  [#text(8pt, weight: "bold")[Параметр расчета]], [#text(8pt, weight: "bold")[Значение]], [#text(8pt, weight: "bold")[Как считаем]],
  [#text(8.5pt)[Спрос в вашем районе]], [#text(8.5pt)[~[[CLIENT_LEADS]] обр./мес]], [#text(8pt, fill: rgb("64748B"))[Поисковый гео-трафик в радиусе 1.5 км]],
  [#text(8.5pt)[Дефицит видимости профиля]], [#text(8.5pt)[[[DEV]]%]], [#text(8pt, fill: rgb("64748B"))[100% минус текущий балл ([[SCORE]])]],
  [#text(8.5pt)[Клиенты, ушедшие к соседям]], [#text(8.5pt)[~[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]]], [#text(8pt, fill: rgb("64748B"))[Спрос района × Дефицит видимости]],
  [#text(8.5pt)[Базовый чек первого визита]], [#text(8.5pt)[[[CLIENT_CHECK_FMT]]~₽]], [#text(8pt, fill: rgb("64748B"))[Средняя стоимость первого обращения]],
  [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[Прямые потери в месяц]], [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]], [#text(8pt, weight: "bold", fill: rgb("9F1239"))[Недополученная выручка первого визита]]
)

#v(2pt)
#text(7.5pt, fill: rgb("64748B"), style: "italic")[
  \* Расчет выполнен консервативно — только по первому визиту. С учетом повторных визитов и прикрепления клиентов ([[CLIENT_LTV]]~мес.) совокупный отток выручки к конкурентам составляет до *[[LTV_LOSS_FMT]]~₽ в год*.
]

#v(8pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 3pt, inset: 8pt)[
  #text(8pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка #strong[[[SCORE]] / 100] отражает исключительно техническое ранжирование карточки алгоритмами Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]].
  ]
]

#pagebreak()

// ==========================================
// СТР. 3 ТОЧКИ СЛИВА ТРАФИКА
// ==========================================
#heading(level: 2)[Три главные причины потери клиентов]
#v(6pt)
#text(9.5pt, fill: rgb("475569"))[Почему потенциальные клиенты из вашего района уходят к конкурентам:]
#v(10pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 12pt)[
  #text(11pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. В поиске не видны ключевые и маржинальные услуги]
  #v(5pt)
  #text(9pt, fill: rgb("475569"))[Когда житель района ищет конкретную услугу (например, [[SERVICE_EXAMPLE]]), Яндекс не показывает вашу компанию в топе. В карточке не выведен понятный прейскурант и фото работ, поэтому клиенты сразу переходят к вашим соседям[[COMP_SAFE]].]
]
#v(9pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 12pt)[
  #text(11pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер при попытке связаться или записаться]
  #v(5pt)
  #text(9pt, fill: rgb("475569"))[Клиентам неудобно звонить по телефону вслепую. Если в профиле нет кнопки быстрой онлайн-записи или прямого перехода в мессенджер к администратору, большинство людей закрывают карточку и уходят к тем, к кому проще записаться.]
]
#v(9pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 12pt)[
  #text(11pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Профиль выглядит «неактивным» для поисковых систем]
  #v(5pt)
  #text(9pt, fill: rgb("475569"))[Если карточка не обновляется, а на отзывы нет официальных ответов руководства, поисковая система считает организацию пассивной и намеренно опускает ее в выдаче, продвигая более активных конкурентов.]
]

#pagebreak()

// ==========================================
// СТР. 4 ДОРОЖНАЯ КАРТА И СЛЕДУЮЩИЙ ШАГ
// ==========================================
#heading(level: 2)[План устранения кассового разрыва]
#v(6pt)
#text(9.5pt, fill: rgb("475569"))[Инженерный план возврата поискового трафика в кассу организации:]
#v(10pt)

#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
      #text(8pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 1: СРОЧНО]
      #v(2pt)
      #text(11pt, weight: "bold", fill: rgb("0A1128"))[3–5 дней]
      #v(3pt)
      #text(8pt, fill: rgb("475569"))[Связка прайс-листа с поисковыми кластерами Яндекса, ликвидация конфликтов гео-данных и дублей.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 9pt)[
      #text(8pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 2: ЗАХВАТ]
      #v(2pt)
      #text(12pt, weight: "bold", fill: rgb("8B7355"))[14 дней]
      #v(3pt)
      #text(8pt, fill: rgb("0A1128"), weight: "bold")[Бесшовная онлайн-запись, разметка витрины для нейросетей Яндекса, семантика специалистов.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
      #text(8pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 3: ЛИДЕРСТВО]
      #v(2pt)
      #text(11pt, weight: "bold", fill: rgb("0A1128"))[Регулярно]
      #v(3pt)
      #text(8pt, fill: rgb("475569"))[Обучение YandexGPT через структуру ответов, защита от правок конкурентов, ТОП-3 района.]
    ]
  ]
)

#v(10pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(8.5pt, fill: rgb("334155"))[
    *Экономика окупаемости:* При текущих потерях порядка *[[REV_LOSS_FMT]]~₽/мес*, возврат даже 6–8 первичных клиентов полностью окупает любые вложения в профессиональную настройку уже в первые 30 дней.
  ]
]

#v(10pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 12pt)[
  #grid(
    columns: (2.3fr, 1fr),
    gutter: 12pt,
    [
      #text(10pt, weight: "bold", fill: rgb("FFFFFF"))[Получить пошаговый план исправления (ТЗ)] \
      #v(3pt)
      #text(8.5pt, fill: rgb("CBD5E1"))[Напишите в Telegram — пришлем короткое 3-минутное видео по вашей карточке с разбором скрытых технических ошибок профиля.]
    ],
    [
      #align(center + horizon)[
        #rect(fill: rgb("1E293B"), stroke: 0.5pt + rgb("8B7355"), radius: 3pt, inset: 8pt)[
          #text(8.5pt, weight: "bold", fill: rgb("F1F5F9"))[Telegram:\ #text(fill: rgb("D97706"))[\@paulvenkov]]
        ]
      ]
    ]
  )
]
