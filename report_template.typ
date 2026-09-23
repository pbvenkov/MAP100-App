#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.5cm, top: 2.5cm, bottom: 2.5cm),
  header: [
    #set text(8pt, fill: rgb("#64748B")) // Благородный серый (Slate 500)
    #grid(
      columns: (1fr, 1fr),
      align(left)[*PIN100 Analytics* | Независимый аудит гео-выдачи],
      align(right)[Конфиденциально. Только для руководства.]
    )
    #v(4pt)
    #line(length: 100%, stroke: 0.5pt + rgb("#E2E8F0"))
  ],
  footer: [
    #set text(8pt, fill: rgb("#94A3B8"))
    #line(length: 100%, stroke: 0.5pt + rgb("#E2E8F0"))
    #v(4pt)
    #grid(
      columns: (3fr, 1fr),
      align(left)[Сгенерировано аналитической платформой. Предназначено для внутреннего использования.],
      align(right)[Стр. #counter(page).display()]
    )
  ]
)

// Базовые настройки текста: выравнивание по ширине, удобный интерлиньяж
#set text(font: ("Roboto", "Arial", "PT Sans", "Helvetica"), size: 11pt, lang: "ru")
#set par(justify: true, leading: 0.65em)

// Динамический массив всех ошибок (Python будет подставлять сюда данные)
#let gaps = (
  [[GAPS_ARRAY]]
)

// ==========================================
// СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ (THE HOOK)
// ==========================================
#align(center)[
  #v(2em)
  #text(size: 26pt, weight: "black", fill: rgb("#1E3A8A"))[PIN100 ANALYTICS]\
  #v(1em)
  #text(size: 18pt, weight: "bold", fill: rgb("#1e293b"))[Аналитическое заключение:]\
  #text(size: 15pt, fill: rgb("#334155"))[Где профиль теряет первичных клиентов]\
  #v(0.5em)
  #text(size: 12pt, fill: rgb("#64748b"))[Расчет упущенной выручки локации и перетока спроса к конкурентам]
]

#v(4em)

#rect(
  width: 100%,
  fill: rgb("#F8FAFC"), // Светло-серо-голубой фон (Slate 50)
  stroke: 1pt + rgb("#E2E8F0"),
  radius: 6pt,
  inset: 18pt,
  [
    #grid(
      columns: (1fr, 2.5fr),
      row-gutter: 1.2em,
      [*Организация:*], [*[[TITLE]]*],
      [*Направление:*], [[[NICHE]]],
      [*Дата фиксации данных:*], [[[DATE]]]
    )
  ]
)

#v(4em)

#text(size: 14pt, weight: "bold", fill: rgb("#0f172a"))[Практическая ценность отчета]
#v(0.5em)
Отчет вскрывает скрытые программные фильтры Яндекс Карт, из-за которых горячие клиенты вашего района уходят к ближайшим конкурентам. В документе нет общих советов по SMM или платной рекламе: здесь зафиксированы конкретные алгоритмические уязвимости профиля и рассчитана точная упущенная выручка бизнеса.

#pagebreak(weak: true)

// ==========================================
// СТРАНИЦА 2: РЕЗЮМЕ И ЭКОНОМИКА
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("#1E3A8A"))[Резюме для руководителя]
#v(1em)

#grid(
  columns: (1fr, 1fr),
  column-gutter: 1.5em,
  rect(width: 100%, fill: rgb("#[[SCORE_COLOR]]").lighten(85%), stroke: 1pt + rgb("#[[SCORE_COLOR]]"), radius: 6pt, inset: 15pt)[
    #text(size: 10pt, fill: rgb("#475569"))[ГОТОВНОСТЬ К ПРИЕМУ ТРАФИКА]\
    #v(0.5em)
    #text(size: 26pt, weight: "bold", fill: rgb("#[[SCORE_COLOR]]"))[[[SCORE]] / 100]\
    #text(size: 9.5pt, fill: rgb("#64748b"))[Балл конкурента-лидера: [[COMPETITOR_SCORE]] / 100]
  ],
  rect(width: 100%, fill: rgb("#FEF2F2"), stroke: 1pt + rgb("#EF4444"), radius: 6pt, inset: 15pt)[
    #text(size: 10pt, fill: rgb("#475569"))[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]\
    #v(0.5em)
    #text(size: 26pt, weight: "bold", fill: rgb("#EF4444"))[[[REV_LOSS_FMT]] ₽/мес]\
    #text(size: 9.5pt, fill: rgb("#64748b"))[Консервативная оценка первого визита]
  ]
)

#v(2em)

#text(size: 14pt, weight: "bold", fill: rgb("#0f172a"))[Критический вывод анализа]
#v(0.5em)
[[EXECUTIVE_SUMMARY]]

#v(2em)

#text(size: 14pt, weight: "bold", fill: rgb("#0f172a"))[Воронка потерь: где именно карточка теряет клиентов]
#v(1em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1em,
  rect(width: 100%, fill: rgb("#F8FAFC"), stroke: 1pt + rgb("#E2E8F0"), radius: 4pt, inset: 12pt)[
    *1. ТРАФИК ЛИДЕРОВ*\
    #text(size: 14pt, weight: "bold", fill: rgb("#1E3A8A"))[[[POTENTIAL_LEADS]] обр.]\
    #text(size: 9pt, fill: rgb("#475569"))[Медиана прямых контактов в ТОП-3 локации.]
  ],
  rect(width: 100%, fill: rgb("#F8FAFC"), stroke: 1pt + rgb("#E2E8F0"), radius: 4pt, inset: 12pt)[
    *2. ЭКРАННЫЙ ФИЛЬТР*\
    #text(size: 14pt, weight: "bold", fill: rgb("#1E3A8A"))[Отказ от контакта]\
    #text(size: 9pt, fill: rgb("#475569"))[Часть людей уходит из-за технических недочетов.]
  ],
  rect(width: 100%, fill: rgb("#FEF2F2"), stroke: 1pt + rgb("#FCA5A5"), radius: 4pt, inset: 12pt)[
    *3. УХОД К СОСЕДЯМ*\
    #text(size: 14pt, weight: "bold", fill: rgb("#DC2626"))[[[LOST_LEADS]] [[TABLE_DECLENSION]]]\
    #text(size: 9pt, fill: rgb("#475569"))[Ежемесячно перетекают к активным конкурентам.]
  ]
)

#v(2em)
#rect(width: 100%, fill: rgb("#F1F5F9"), stroke: none, radius: 4pt, inset: 10pt)[
  #text(size: 8.5pt, fill: rgb("#475569"))[
    * Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом повторных визитов и лояльности клиентов (LTV: [[CLIENT_LTV]] мес.) годовой отток районного бюджета составляет до *[[LTV_LOSS_FMT]] ₽*. Источник бенчмарков: [[BENCHMARK_SOURCE]].\
    \
    *Важное примечание:* Оценка [[SCORE]]/100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
  ]
]

#pagebreak(weak: true)

// ==========================================
// СТРАНИЦА 3: УЯЗВИМОСТИ (THE PROOF)
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("#1E3A8A"))[Реестр алгоритмических уязвимостей]
#v(0.5em)
#text(size: 11pt)[
  Ниже представлен полный перечень параметров вашей карточки, которые не соответствуют стандартам поисковых алгоритмов. Именно эти факторы являются причиной критической утечки первичного трафика.
]
#v(1.5em)

// ДИНАМИЧЕСКИЙ ЦИКЛ ПО ВСЕМ ОШИБКАМ
#for gap in gaps [
  #block(
    fill: rgb("#FEF2F2"), 
    width: 100%,
    inset: (x: 14pt, y: 14pt),
    radius: 6pt,
    stroke: 1pt + rgb("#FECACA"), 
    [
      #text(weight: "bold", size: 12pt, fill: rgb("#B91C1C"))[❌ #gap.title]
      #v(0.6em)
      #text(size: 10.5pt, fill: rgb("#334155"))[#gap.desc]
    ]
  )
  #v(0.8em)
]

#pagebreak(weak: true)

// ==========================================
// СТРАНИЦА 4: ПЛАН И ЗАКРЫТИЕ НА СДЕЛКУ (THE CURE)
// ==========================================
#text(size: 18pt, weight: "bold", fill: rgb("#1E3A8A"))[Как устранить уязвимости и вернуть трафик?]
#v(0.5em)
Данный отчет демонстрирует текущие зоны потерь. Оставляя профиль в текущем состоянии, бизнес продолжает ежедневно спонсировать конкурентов своими потенциальными клиентами. 

Возврат первичного спроса требует системной работы с семантическим ядром, поведенческими факторами и интеграциями:
#v(1.5em)

#grid(
  columns: (1fr, 1fr, 1fr),
  column-gutter: 1.5em,
  [
    #text(fill: rgb("#1E3A8A"), weight: "bold")[ЭТАП 1: СТАРТ]\
    #text(size: 9pt, weight: "bold", fill: rgb("#64748b"))[Базовая гигиена]\
    #v(0.5em)
    #text(size: 10pt)[Привязка услуг к профильным запросам, исправление меток входа и алгоритмической структуры.]
  ],
  [
    #text(fill: rgb("#1E3A8A"), weight: "bold")[ЭТАП 2: ОЦИФРОВКА]\
    #text(size: 9pt, weight: "bold", fill: rgb("#64748b"))[Конверсионные триггеры]\
    #v(0.5em)
    #text(size: 10pt)[Подключение модулей захвата лидов, оформление цифровых карточек команды, обоснование прайса.]
  ],
  [
    #text(fill: rgb("#1E3A8A"), weight: "bold")[ЭТАП 3: ЗАКРЕПЛЕНИЕ]\
    #text(size: 9pt, weight: "bold", fill: rgb("#64748b"))[Доверие Яндекса]\
    #v(0.5em)
    #text(size: 10pt)[Регламент ответов на отзывы, защита от спам-правок, удержание карточки в ТОП-3 выдачи района.]
  ]
)

#v(2em)
#rect(width: 100%, fill: rgb("#FEF2F2"), stroke: 1pt + rgb("#EF4444"), radius: 6pt, inset: 15pt)[
  *ЦЕНА НЕДЕЛИ ПРОМЕДЛЕНИЯ: [[WEEKLY_LOSS_FMT]] ₽ / нед*\
  #text(size: 10pt, fill: rgb("#475569"))[Сумма, которая безвозвратно переходит к прямым конкурентам локации, пока технические ошибки профиля не устранены.]\
  #v(0.5em)
  *БЫСТРАЯ ОКУПАЕМОСТЬ:*\
  #text(size: 10pt, fill: rgb("#475569"))[Всего 2-3 первичных визита полностью перекрывают любые затраты на профессиональную оптимизацию профиля под ключ.]
]

#v(2em)
#line(length: 100%, stroke: 1pt + rgb("#E2E8F0"))
#v(1em)

#text(size: 16pt, weight: "bold", fill: rgb("#0f172a"))[Обсудить интеграцию изменений]
#v(0.5em)
Чтобы получить точный расчет стоимости оцифровки вашего гео-профиля "под ключ", свяжитесь с нашим аналитическим центром.

#v(1em)
#grid(
  columns: (1fr, 1fr),
  [
    *Павел Венков*\
    #text(size: 10pt, fill: rgb("#64748b"))[Руководитель агентства PIN100\
    Оцифровка и аналитика гео-карт]
  ],
  align(right)[
    #text(size: 10.5pt)[
      🌐 Сайт: *pin100.ru*\
      💬 Telegram: *t.me/paulvenkov*\
      📞 Телефон: *+7 (921) 966-26-89*
    ]
  ]
)
