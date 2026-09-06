#set document(title: "Аналитическое Заключение - [[TITLE]]", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 20mm),
  footer: [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Протокол алгоритмической оценки гео-выдачи
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
#v(90pt)
#text(12pt, fill: rgb("8B7355"), weight: "bold", tracking: 2pt)[PIN100 ANALYTICS]
#v(8pt)
#text(25pt, weight: "bold", font: ("Playfair Display", "Georgia", "serif"), fill: rgb("0A1128"))[Аналитическое Заключение:\ Оцифровка потерь первичного потока]
#v(10pt)
#line(length: 60mm, stroke: 1.5pt + rgb("8B7355"))
#v(25pt)
#text(11pt, fill: rgb("475569"))[
  Организация: #strong[[[TITLE]]] \
  Сегмент: #strong[[[NICHE]]] \
  Дата фиксации данных: #strong[[[DATE]]]
]
#v(35pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(8.5pt, fill: rgb("64748B"))[
    *Методология аудита:* Оценка готовности карточки к перехвату локального спроса по *79 техническим параметрам* поисковой оптимизации, алгоритмов YandexGPT, полноты витрины и конверсионного слоя.
  ]
]

#pagebreak()

// ==========================================
// СТР. 2 EXECUTIVE SUMMARY
// ==========================================
#heading(level: 2)[Резюме для руководителя]
#v(6pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 14pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
      #text(8pt, fill: rgb("64748B"), weight: "bold", tracking: 0.5pt)[ИНДЕКС ВИДИМОСТИ КАРТОЧКИ]
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
  #text(9pt, fill: rgb("334155"))[Прямо сейчас профиль скрыт от *[[DEV]]% целевых клиентов* вашего района. Из-за технических недочетов в карточке вы ежемесячно отдаете конкурентам локации около *[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]*.]
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
  [#text(8pt, weight: "bold")[Параметр расчета]], [#text(8pt, weight: "bold")[Значение]], [#text(8pt, weight: "bold")[Методика расчета]],
  [#text(8.5pt)[Пул спроса лидеров района]], [#text(8.5pt)[~[[CLIENT_LEADS]] обр./мес]], [#text(8pt, fill: rgb("64748B"))[Трафик ТОП-3 организаций локации]],
  [#text(8.5pt)[Дефицит видимости профиля]], [#text(8.5pt)[[[DEV]]%]], [#text(8pt, fill: rgb("64748B"))[100% минус текущий балл ([[SCORE]])]],
  [#text(8.5pt)[Клиенты, ушедшие к конкурентам]], [#text(8.5pt)[~[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]]], [#text(8pt, fill: rgb("64748B"))[Спрос лидеров × Дефицит видимости]],
  [#text(8.5pt)[Базовый чек первого визита]], [#text(8.5pt)[[[CLIENT_CHECK_FMT]]~₽]], [#text(8pt, fill: rgb("64748B"))[Консервативный порог первого чека]],
  [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[Прямые потери в месяц]], [#text(8.5pt, weight: "bold", fill: rgb("9F1239"))[- [[REV_LOSS_FMT]]~₽/мес]], [#text(8pt, weight: "bold", fill: rgb("9F1239"))[Недополученная выручка первого визита]]
)

#v(2pt)
#text(7.5pt, fill: rgb("64748B"), style: "italic")[
  \* Расчет выполнен строго консервативно по первому чеку. С учетом повторных визитов и LTV-прикрепления ([[CLIENT_LTV]]~мес.) суммарный отток выручки в пользу прямых конкурентов района составляет до *[[LTV_LOSS_FMT]]~₽ в год*.
]

#v(6pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 3pt, inset: 8pt)[
  #text(8pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Индекс #strong[[[SCORE]] / 100] фиксирует только поисковую видимость карточки в алгоритмах Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]].
  ]
]

#pagebreak()

// ==========================================
// СТР. 3 ТОЧКИ СЛИВА ТРАФИКА
// ==========================================
#heading(level: 2)[Три ключевые причины потери целевых обращений]
#v(4pt)
#text(9pt, fill: rgb("475569"))[Инженерный анализ барьеров, из-за которых спрос района забирают конкуренты[[COMP_SAFE]]:]
#v(8pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. Отсутствие семантической связки витрины и поисковых кластеров]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Факт:* Когда житель района вбивает целевой запрос (например, *[[SERVICE_EXAMPLE]]*), поисковый робот сканирует прайс-лист карточки. \
    *Следствие:* Если в профиле нет структурированного прейскуранта с фото и ценами, алгоритм исключает карточку из специализированной выдачи и отдает горячего клиента конкурентам района.
  ]
]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер конверсии при попытке связаться или записаться]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Факт:* Более 60% мобильного трафика на картах предпочитают мгновенное бронирование без голосового звонка. \
    *Следствие:* При отсутствии бесшовной кнопки онлайн-записи или прямого перехода в мессенджер к администратору, конверсия из просмотра карточки в визит падает на 28–35%. Клиент закрывает профиль и уходит к тем, к кому записаться проще в 1 клик.
  ]
]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(10.5pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Сигнал пассивности для нейросетевых алгоритмов YandexGPT]
  #v(4pt)
  #text(8.5pt, fill: rgb("475569"))[
    *Факт:* Поисковые алгоритмы оценивают регулярность обновления карточки и тональность диалога в отзывах. \
    *Следствие:* Отсутствие регламентированных ответов руководства и пассивная новостная лента понижают авторитет карточки (Trust Score). Яндекс перенаправляет показы более активным профилям локации.
  ]
]

#pagebreak()

// ==========================================
// СТР. 4 ДОРОЖНАЯ КАРТА И СЛЕДУЮЩИЙ ШАГ
// ==========================================
#heading(level: 2)[План ликвидации кассового разрыва]
#v(4pt)
#text(9pt, fill: rgb("475569"))[Инженерная дорожная карта возврата локального поискового потока:]
#v(8pt)

#grid(
  columns: (1fr, 1.15fr, 1fr),
  gutter: 8pt,
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 1: ЛИКВИДАЦИЯ УТЕЧЕК]
      #v(2pt)
      #text(10.5pt, weight: "bold", fill: rgb("0A1128"))[3–5 дней]
      #v(3pt)
      #text(7.5pt, fill: rgb("475569"))[Связка прайс-листа с поисковыми кластерами, устранение гео-конфликтов и технических дублей.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("F8FAFC"), stroke: 1.5pt + rgb("8B7355"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("8B7355"))[ЭТАП 2: ЗАХВАТ ВЫДАЧИ]
      #v(2pt)
      #text(11.5pt, weight: "bold", fill: rgb("8B7355"))[14 дней]
      #v(3pt)
      #text(7.5pt, fill: rgb("0A1128"), weight: "bold")[Бесшовная онлайн-запись, разметка витрины для нейросетей, семантика специалистов.]
    ]
  ],
  [
    #rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 8pt)[
      #text(7.5pt, weight: "bold", fill: rgb("64748B"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ]
      #v(2pt)
      #text(10.5pt, weight: "bold", fill: rgb("0A1128"))[Постоянно]
      #v(3pt)
      #text(7.5pt, fill: rgb("475569"))[Обучение YandexGPT через ответы, защита от правок конкурентов, стабильный ТОП-3 района.]
    ]
  ]
)

#v(8pt)
#rect(width: 100%, fill: rgb("FFF1F2"), stroke: 0.5pt + rgb("FECDD3"), radius: 4pt, inset: 9pt)[
  #text(8.5pt, fill: rgb("9F1239"))[
    *Цена бездействия (Cost of Inaction):* Каждая неделя промедления с устранением технических барьеров обходится организации примерно в *[[WEEKLY_LOSS_FMT]]~₽*, которые безвозвратно переходят к вашим прямым конкурентам.
  ]
]

#v(6pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 9pt)[
  #text(8pt, fill: rgb("334155"))[
    *Экономика возврата:* При текущих потерях порядка *[[REV_LOSS_FMT]]~₽/мес*, привлечение даже 5–7 дополнительных клиентов полностью окупает любые сервисные затраты на настройку уже в первый месяц.
  ]
]

#v(8pt)
#rect(width: 100%, fill: rgb("0A1128"), radius: 4pt, inset: 11pt)[
  #grid(
    columns: (2.3fr, 1fr),
    gutter: 10pt,
    [
      #text(9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Получить пошаговый план внедрения (ТЗ)] \
      #v(2pt)
      #text(8pt, fill: rgb("CBD5E1"))[Напишите в Telegram — подготовим 3-минутное персональное видео с разбором скрытых программных ошибок карточки.]
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
