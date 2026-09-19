#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.5cm),
  header: align(right)[
    #text(8pt, fill: luma(120))[PIN 100 Analytics | Независимый аудит гео-выдачи]
  ],
  footer: align(center)[
    #text(8pt, fill: luma(150))[
      Сгенерировано аналитической платформой. Документ предназначен исключительно для внутреннего использования руководством.
      #h(1fr)
      Стр. #counter(page).display()
    ]
  ]
)

#set text(font: "Arial", size: 11pt, lang: "ru")

// ==========================================
// СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ
// ==========================================
#align(center)[
  #text(size: 24pt, weight: "bold", fill: rgb("1e3a8a"))[PIN 100 ANALYTICS]\
  #v(1em)
  #text(size: 18pt, weight: "bold")[Аналитическое заключение:]\
  #text(size: 14pt)[Где профиль теряет первичных клиентов]\
  #text(size: 12pt, fill: luma(100))[Расчет упущенной выручки локации и перетока спроса к конкурентам]
]

#v(3em)

#rect(
  width: 100%,
  fill: luma(245),
  stroke: luma(200),
  radius: 4pt,
  inset: 15pt,
  [
    #grid(
      columns: (1fr, 2fr),
      row-gutter: 1em,
      [*Организация:*], [*[[TITLE]]*],
      [*Направление:*], [[[NICHE]]],
      [*Дата фиксации данных:*], [[[DATE]]]
    )
  ]
)

#v(3em)

#text(size: 14pt, weight: "bold")[Практическая ценность отчета:]
#v(0.5em)
Отчет показывает скрытые программные фильтры Яндекс Карт, из-за которых готовые к обращению клиенты района уходят к ближайшим конкурентам. Здесь нет общих советов по рекламе: зафиксированы конкретные барьеры конверсии в профиле и рассчитана упущенная выручка бизнеса без затрат на платный трафик.

#pagebreak()

// ==========================================
// СТРАНИЦА 2: РЕЗЮМЕ И ЭКОНОМИКА
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("1e3a8a"))[Резюме для руководителя]
#v(1em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 2em,
  rect(width: 100%, fill: rgb("[[SCORE_COLOR]]").lighten(80%), stroke: rgb("[[SCORE_COLOR]]"), radius: 4pt, inset: 15pt)[
    #text(size: 10pt)[ГОТОВНОСТЬ К ПРИЕМУ ТРАФИКА]\
    #text(size: 24pt, weight: "bold", fill: rgb("[[SCORE_COLOR]]"))[[[SCORE]] / 100]\
    #text(size: 9pt)[Балл конкурента-лидера: [[COMPETITOR_SCORE]] / 100]
  ],
  rect(width: 100%, fill: rgb("fef2f2"), stroke: rgb("ef4444"), radius: 4pt, inset: 15pt)[
    #text(size: 10pt)[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]\
    #text(size: 24pt, weight: "bold", fill: rgb("ef4444"))[[[REV_LOSS_FMT]] ₽/мес]\
    #text(size: 9pt)[Консервативная оценка первого визита]
  ]
)

#v(2em)

#text(size: 14pt, weight: "bold")[Критический вывод анализа:]
#v(0.5em)
[[EXECUTIVE_SUMMARY]]

#v(2em)

#text(size: 14pt, weight: "bold")[Воронка потерь: где именно карточка теряет клиентов]
#v(1em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1em,
  rect(width: 100%, stroke: luma(200), inset: 10pt)[
    *1. ТРАФИК ЛИДЕРОВ*\
    *[[POTENTIAL_LEADS]] обр.*\
    #text(size: 9pt)[Медиана прямых контактов в ТОП-3 локации.]
  ],
  rect(width: 100%, stroke: luma(200), inset: 10pt)[
    *2. ЭКРАННЫЙ ФИЛЬТР*\
    *Отказ от контакта*\
    #text(size: 9pt)[Часть людей уходит из-за технических недочетов карточки.]
  ],
  rect(width: 100%, stroke: rgb("ef4444"), fill: rgb("fef2f2"), inset: 10pt)[
    *3. УХОД К СОСЕДЯМ*\
    *[[LOST_LEADS]] [[TABLE_DECLENSION]]*\
    #text(size: 9pt)[Ежемесячно перетекают к активным конкурентам.]
  ]
)

#v(2em)
#text(size: 8pt, fill: luma(100))[
  * Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом повторных визитов и лояльности клиентов (LTV: [[CLIENT_LTV]] мес.) годовой отток районного бюджета составляет до [[LTV_LOSS_FMT]] ₽. Источник бенчмарков: [[BENCHMARK_SOURCE]].\
  \
  Важное примечание: Оценка [[SCORE]] / 100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
]

#pagebreak()

// ==========================================
// СТРАНИЦА 3: УЯЗВИМОСТИ (СВЕТОФОР)
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("1e3a8a"))[[[PAGE_3_HEADING]]]
#v(0.5em)
#text(size: 12pt)[[[PAGE_3_SUBTITLE]]]
#v(2em)

#rect(width: 100%, fill: rgb("[[FAIL_1_COLOR]]").lighten(90%), stroke: rgb("[[FAIL_1_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("[[FAIL_1_COLOR]]"))[1. [[FAIL_1_TITLE]]]\
  #v(0.5em)
  [[FAIL_1_DESC]]
]
#v(1em)

#rect(width: 100%, fill: rgb("[[FAIL_2_COLOR]]").lighten(90%), stroke: rgb("[[FAIL_2_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("[[FAIL_2_COLOR]]"))[2. [[FAIL_2_TITLE]]]\
  #v(0.5em)
  [[FAIL_2_DESC]]
]
#v(1em)

#rect(width: 100%, fill: rgb("[[FAIL_3_COLOR]]").lighten(90%), stroke: rgb("[[FAIL_3_COLOR]]"), radius: 4pt, inset: 15pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("[[FAIL_3_COLOR]]"))[3. [[FAIL_3_TITLE]]]\
  #v(0.5em)
  [[FAIL_3_DESC]]
]

#pagebreak()

// ==========================================
// СТРАНИЦА 4: ДОРОЖНАЯ КАРТА И КОНТАКТЫ
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("1e3a8a"))[Дорожная карта перехвата локального спроса]
#v(0.5em)
Пошаговый план возврата первичных клиентов в кассу организации:
#v(1.5em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.5em,
  [
    *ЭТАП 1: СТАРТ*\
    *3-5 дней*\
    #text(size: 10pt)[Привязка услуг к запросам, исправление меток входа, парковки и дублирующих адресов.]
  ],
  [
    *ЭТАП 2: ОЦИФРОВКА*\
    *14 дней*\
    #text(size: 10pt)[Подключение инструментов конверсии, оформление карточек команды, наглядный прейскурант.]
  ],
  [
    *ЭТАП 3: ЗАКРЕПЛЕНИЕ*\
    *Постоянно*\
    #text(size: 10pt)[Регламент ответов на отзывы, защита от недостоверных правок, удержание в ТОП-3 района.]
  ]
)

#v(2em)
#rect(width: 100%, fill: rgb("fef2f2"), stroke: rgb("ef4444"), radius: 4pt, inset: 15pt)[
  *ЦЕНА НЕДЕЛИ ПРОМЕДЛЕНИЯ: [[WEEKLY_LOSS_FMT]] ₽ / нед*\
  #text(size: 10pt)[Сумма, которая безвозвратно переходит к прямым конкурентам локации.]\
  #v(0.5em)
  *БЫСТРАЯ ОКУПАЕМОСТЬ:*\
  #text(size: 10pt)[Всего 2-3 первичных визита полностью перекрывают любые затраты на профессиональную оптимизацию профиля.]
]

#v(2em)
#line(length: 100%, stroke: 0.5pt + luma(200))
#v(1em)

#text(size: 16pt, weight: "bold")[Регламент внедрения изменений]
#v(0.5em)
[[RISK_REVERSAL]]

#v(2em)
С уважением, \
*Павел Венков*\
Руководитель агентства PIN 100 \

#v(1em)
*Контакты для связи:*\
🌐 Сайт: pin100.ru \
💬 Telegram: t.me/paulvenkov \
📞 Телефон: +7 (921) 966-26-89
