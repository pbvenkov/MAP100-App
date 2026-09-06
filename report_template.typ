#set document(title: "Аналитическое Заключение - [[TITLE]]", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 20mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Независимый аудит поисковой гео-выдачи
    #h(1fr)
    #context [Стр. #counter(page).display("1")]
  ]
)

#set text(font: ("Inter", "Arial", "sans-serif"), size: 10pt, fill: rgb("334155"), lang: "ru")
#set par(leading: 0.58em)
#show heading: set text(font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))

// ==========================================
// СТР. 1: ОБЛОЖКА И МЕТОДОЛОГИЯ
// ==========================================
#v(90pt)
#text(12pt, fill: rgb("8B7355"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(8pt)
#text(24pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитическое Заключение:\ Оцифровка потерь первичного потока]
#v(10pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(25pt)
#text(11pt, fill: rgb("475569"))[
  Организация: #strong[[[TITLE]]] \
  Направление: #strong[[[NICHE]]] \
  Дата фиксации данных: #strong[[[DATE]]]
]
#v(35pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(8.5pt, fill: rgb("64748B"))[
    *Методология аудита:* Оценка готовности профиля к приему первичных обращений по *79 параметрам поисковой доступности*, полноты прейскуранта и простоты записи. Анализ учитывает отраслевые стандарты размещения информации об услугах и квалификации специалистов.
  ]
]

#pagebreak()

// ==========================================
// СТР. 2: РЕЗЮМЕ ДЛЯ РУКОВОДИТЕЛЯ
// ==========================================
#heading(level: 2)[Резюме для руководителя]
#v(6pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
      #text(8pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ВИДИМОСТЬ КАРТОЧКИ В ПОИСКЕ]
      \
      #v(4pt)
      #text(22pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]] / 100]
      #v(2pt)
      #text(8pt, fill: rgb("94A3B8"), style: "italic")[Оценка по 79 факторам ранжирования]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
      #text(8pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]
      \
      #v(4pt)
      #text(20pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]
      #v(2pt)
      #text(8pt, fill: rgb("94A3B8"), style: "italic")[Консервативная оценка первого визита]
    ]
  ]
)

#v(6pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[Критический вывод анализа:]
  #v(3pt)
  #text(9pt, fill: rgb("334155"))[Прямо сейчас профиль скрыт от *[[DEV]]% целевых клиентов* вашего района. Из-за технических недочетов в оформлении карточки вы каждый месяц отдаете конкурентам локации около *[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]*.]
]

#v(6pt)
#text(9.5pt, weight: "bold", fill: rgb("0A1128"))[Прозрачный расчет потерь (юнит-экономика локации):]
#v(3pt)

#table(
  columns: (1.3fr, 1fr, 1.4fr),
  stroke: 0.5pt + rgb("E2E8F0"),
  fill: (col, row) => if row == 0 { rgb("F1F5F9") } else if row == 5 { rgb("FFF1F2") } else { none },
  inset: 6pt,
  align: (left + horizon, center + horizon, left + horizon),
  [#text(8pt, weight: "bold")[Параметр расчета]], [#text(8pt, weight: "bold")[Значение]], [#text(8pt, weight: "bold")[Как считаем]],
  [#text(8.5pt)[Пул спроса лидеров района]], [#text(8.5pt)[~[[CLIENT_LEADS]] обр./мес]], [#text(8pt, fill: rgb("64748B"))[Поток обращений в ТОП-3 клиники локации]],
  [#text(8.5pt)[Дефицит видимости профиля]], [#text(8.5pt)[[[DEV]]%]], [#text(8pt, fill: rgb("64748B"))[100% минус текущий балл ([[SCORE]])]],
  [#text(8.5pt)[Клиенты, ушедшие к конкурентам]], [#text(8.5pt)[~[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]]], [#text(8pt, fill: rgb("64748B"))[Спрос лидеров × Дефицит видимости]],
  [#text(8.5pt)[Базовый чек первого визита]], [#text(8.5pt)[[[CLIENT_CHECK_FMT]]~₽]], [#text(8pt, fill: rgb("64748B"))[Консервативный порог первого визита]],
  [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[Прямые потери в месяц]], [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]], [#text(8pt, weight: "bold", fill: rgb("9F1239"))[Недополученная выручка первого визита]]
)

#v(2pt)
#text(7.5pt, fill: rgb("64748B"), style: "italic")[
  \* Расчет выполнен строго по первому чеку. С учетом повторных визитов и прикрепления клиентов ([[CLIENT_LTV]]~мес.) совокупный отток выручки в пользу прямых конкурентов района составляет до *[[LTV_LOSS_FMT]]~₽ в год*.
]

#v(6pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 3pt, inset: 8pt)[
  #text(8pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка #strong[[[SCORE]] / 100] фиксирует исключительно техническую видимость профиля в поиске Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]]. Это программные особенности поисковой выдачи, которые не зависят от работы администраторов.
  ]
]

#pagebreak()

// ==========================================
// СТР. 3: ТОЧКИ ПОТЕРИ ПАЦИЕНТОВ
// ==========================================
#heading(level: 2)[Три главные причины потери пациентов]
#v(4pt)
#text(9pt, fill: rgb("475569"))[Почему потенциальные клиенты из вашего района уходят к конкурентам[[COMP_SAFE]]:]
#v(8pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. В поиске не видны ключевые услуги и понятные цены]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Как видит пациент:* Когда житель района ищет конкретную помощь (например, *[[SERVICE_EXAMPLE]]*), Яндекс проверяет наличие этих позиций в прейскуранте карточки. \
    *Что происходит в кассе:* Если в профиле нет структурированного списка процедур с ценами и фото, поисковая система исключает организацию из топа выдачи, а пациент сразу уходит в клиники с прозрачным прайсом.
  ]
]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер при попытке связаться или записаться]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Как видит пациент:* Более 60% современных пользователей на картах предпочитают мгновенную онлайн-запись или связь через мессенджер без звонка администратору вслепую. \
    *Что происходит в кассе:* Если кнопки быстрой записи нет, большинство людей закрывают карточку, не совершая звонка, и выбирают организацию, куда записаться можно в 1–2 клика.
  ]
]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Профиль выглядит «неактивным» для поисковых систем]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Как видит поисковик:* Алгоритмы оценивают регулярность обновления карточки и обязательное наличие официальных ответов руководства на отзывы гостей. \
    *Что происходит в кассе:* Отсутствие ответов на отклики и редкое обновление профиля сигнализируют системе о низкой активности. Яндекс намеренно опускает такую организацию в поиске, продвигая активных соседей.
  ]
]

#pagebreak()

// ==========================================
// СТР. 4: ПЛАН ДЕЙСТВИЙ И СЛЕДУЮЩИЙ ШАГ
// ==========================================
#heading(level: 2)[План устранения кассового разрыва]
#v(4pt)
#text(9pt, fill: rgb("475569"))[Пошаговый план возврата районного потока обращений в кассу организации:]
#v(8pt)

#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 1: БЫСТРЫЙ СТАРТ]
      #v(2pt)
      #text(10.5pt, weight: "bold", fill: rgb("0A1128"))[3–5 дней]
      #v(3pt)
      #text(7.5pt, fill: rgb("475569"))[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 2: ПОЛНАЯ ОЦИФРОВКА]
      #v(2pt)
      #text(11.5pt, weight: "bold", fill: rgb("8B7355"))[14 дней]
      #v(3pt)
      #text(7.5pt, fill: rgb("0A1128"), weight: "bold")[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ]
      #v(2pt)
      #text(10.5pt, weight: "bold", fill: rgb("0A1128"))[Постоянно]
      #v(3pt)
      #text(7.5pt, fill: rgb("475569"))[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
    ]
  ]
)

#v(8pt)
#rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 4pt, inset: 9pt)[
  #text(8.5pt, fill: rgb("9F1239"))[
    *Цена бездействия (Cost of Inaction):* Каждая неделя промедления с исправлением технических недочетов обходится организации примерно в *[[WEEKLY_LOSS_FMT]]~₽*, которые безвозвратно переходят к вашим прямым конкурентам.
  ]
]

#v(6pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
  #text(8pt, fill: rgb("334155"))[
    *Экономика окупаемости:* При текущих потерях порядка *[[REV_LOSS_FMT]]~₽/мес*, привлечение даже 4–6 дополнительных первичных клиентов полностью окупает любые сервисные расходы на настройку уже в первые 30 дней.
  ]
]

#v(8pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 11pt)[
  #grid(
    columns: (2.3fr, 1fr),
    gutter: 10pt,
    [
      #text(9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Получить пошаговый план исправления (ТЗ)] \
      #v(2pt)
      #text(8pt, fill: rgb("CBD5E1"))[Напишите в Telegram — пришлем короткое 3-минутное персональное видео по вашей карточке с разбором скрытых технических ошибок профиля.]
    ],
    [
      #align(center + horizon)[
        #rect(fill: rgb("1E293B"), stroke: 0.5pt + rgb("8B7355"), radius: 3pt, inset: 7pt)[
          #text(8pt, weight: "bold", fill: rgb("F1F5F9"))[Telegram:\ #text(fill: rgb("D97706"))[\@paulvenkov]]
        ]
      ]
    ]
  )
]
