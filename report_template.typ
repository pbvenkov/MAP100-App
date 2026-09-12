#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2.5cm),
  header: [
    #set text(8pt, fill: luma(120), font: ("Arial", "sans-serif"))
    #grid(
      columns: (1fr, 1fr),
      align(left)[*PIN100 Analytics* | Конфиденциальный аудит гео-выдачи],
      align(right)[Стр. #context counter(page).display()]
    )
    #v(0.3cm)
    #line(length: 100%, stroke: 0.5pt + luma(200))
  ],
  footer: [
    #set text(7.5pt, fill: luma(150), font: ("Arial", "sans-serif"))
    #align(center)[Сгенерировано аналитической платформой. Документ предназначен исключительно для внутреннего использования руководством.]
  ]
)

// Базовые настройки типографики: читаемый размер, мягкий темный цвет текста
#set text(font: ("Arial", "Liberation Sans", "PT Sans", "sans-serif"), size: 11pt, fill: rgb("#0f172a"), lang: "ru")
#set par(leading: 0.6em, justify: true)

// =========================================================
// СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ
// =========================================================
#v(1cm)
#text(size: 28pt, weight: "bold", fill: rgb("#be123c"))[PIN100 ANALYTICS]
#v(0.5cm)

#text(size: 18pt, weight: "bold")[Аналитическое заключение:\ Где профиль теряет первичных клиентов]
#v(0.3cm)
#text(size: 13pt, fill: luma(80))[Расчет упущенной выручки локации и перетока спроса к конкурентам]

#v(1.5cm)
#rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), radius: 6pt, inset: 1.2cm, width: 100%)[
  #grid(
    columns: (1.2fr, 2fr),
    row-gutter: 1.2em,
    text(weight: "bold")[Организация:], text(weight: "bold", size: 13pt)[[[TITLE]]],
    text(weight: "bold")[Направление:], [[[NICHE]]],
    text(weight: "bold")[Дата фиксации данных:], [[[DATE]]]
  )
]

#v(1cm)
#rect(fill: rgb("#fff1f2"), stroke: 1pt + rgb("#fecdd3"), radius: 4pt, inset: 10pt)[
  #text(size: 9pt, weight: "bold", fill: rgb("#e11d48"))[СТРОГО КОНФИДЕНЦИАЛЬНО. ТОЛЬКО ДЛЯ РУКОВОДСТВА.]
]

#v(1cm)
#text(size: 14pt, weight: "bold")[Практическая ценность отчета:]
#v(0.5cm)
Отчет показывает скрытые программные фильтры Яндекс Карт, из-за которых готовые к обращению клиенты района уходят к ближайшим конкурентам. Здесь нет общих советов по рекламе: зафиксированы конкретные барьеры конверсии в профиле и рассчитана упущенная выручка бизнеса без затрат на платный трафик.

#pagebreak()

// =========================================================
// СТРАНИЦА 2: РЕЗЮМЕ
// =========================================================
#text(size: 18pt, weight: "bold")[Резюме для руководителя]
#v(0.8cm)

#grid(
  columns: (1fr, 1fr),
  gutter: 1cm,
  rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(size: 9pt, weight: "bold", fill: luma(100))[ГОТОВНОСТЬ К ПРИЕМУ ТРАФИКА]
    #v(0.5em)
    #text(size: 26pt, weight: "bold", fill: rgb("#[[SCORE_COLOR]]"))[[[SCORE]]/100]
    #v(0.5em)
    #text(size: 9.5pt, fill: luma(80))[Оценка факторов конверсии и ранжирования]
  ],
  rect(fill: rgb("#fff1f2"), stroke: 1pt + rgb("#ffe4e6"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(size: 9pt, weight: "bold", fill: rgb("#be123c"))[ПРЯМЫЕ ПОТЕРИ ВЫРУЧКИ]
    #v(0.5em)
    #text(size: 26pt, weight: "bold", fill: rgb("#be123c"))[[[REV_LOSS_FMT]] ₽/мес]
    #v(0.5em)
    #text(size: 9.5pt, fill: luma(80))[Консервативная оценка первого визита]
  ]
)

#v(1cm)
#text(size: 14pt, weight: "bold")[Парадокс локального поиска: почему высокого рейтинга больше недостаточно]
#v(0.5em)
Более 65% людей выбирают организацию в мобильных Картах за 40-60 секунд, не переходя на сайт (модель Zero-Click). Высокий рейтинг создает первичное доверие, но современные алгоритмы выдачи отдают верхние позиции карточкам с активным функционалом: мгновенная онлайн-запись, оцифрованный прайс и прямой чат. Карточка без этих инструментов теряет горячих клиентов еще до звонка администратору.

#v(0.8cm)
#rect(stroke: (left: 4pt + rgb("#be123c")), fill: rgb("#fafafa"), inset: 1.2em, width: 100%)[
  #text(weight: "bold", size: 12pt)[Критический вывод анализа:]
  #v(0.5em)
  [[EXECUTIVE_SUMMARY]]
]

#v(0.8cm)
#text(size: 14pt, weight: "bold")[Воронка потерь: где именно карточка теряет клиентов]
#v(0.5em)
#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 0.5cm,
  rect(fill: rgb("#f8fafc"), inset: 12pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", size: 9pt)[1. ТРАФИК ЛИДЕРОВ]
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#2563eb"))[[[CLIENT_LEADS]] обр.]
    #v(0.5em)
    #text(size: 9.5pt)[Медиана прямых контактов (звонки и маршруты) в ТОП-3 локации.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 12pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", size: 9pt)[2. ЭКРАННЫЙ ФИЛЬТР]
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#d97706"))[Отказ от звонка]
    #v(0.5em)
    #text(size: 9.5pt)[65% людей не звонят, если нет онлайн-записи или не виден прайс.]
  ],
  rect(fill: rgb("#fff1f2"), inset: 12pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", size: 9pt)[3. УХОД К СОСЕДЯМ]
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#be123c"))[-[[REV_LOSS_FMT]] ₽]
    #v(0.5em)
    #text(size: 9.5pt)[[[LOST_LEADS]] [[TABLE_DECLENSION]] ежемесячно перетекают к активным конкурентам.]
  ]
)

#v(0.5cm)
#block(breakable: false)[
  #text(size: 8.5pt, fill: luma(120))[
    \* Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом повторных визитов и прикрепления клиентов годовой отток районного бюджета составляет до [[LTV_LOSS_FMT]] ₽. Источник бенчмарков: [[BENCHMARK_SOURCE]].\
    \
    Важное примечание: Оценка [[SCORE]] / 100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
  ]
]

#pagebreak()

// =========================================================
// СТРАНИЦА 3: ТОП ОШИБОК
// =========================================================
#text(size: 18pt, weight: "bold")[[[PAGE_3_HEADING]]]
#v(0.3cm)
#text(size: 12pt)[[[PAGE_3_SUBTITLE]]]
#v(1cm)

#grid(
  columns: (1fr),
  row-gutter: 0.8cm,
  rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), inset: 1.2cm, width: 100%, radius: 6pt)[
    #text(size: 14pt, weight: "bold", fill: rgb("#be123c"))[1. [[FAIL_1_TITLE]]]
    #v(0.8em)
    #text(size: 12pt)[[[FAIL_1_DESC]]]
  ],
  rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), inset: 1.2cm, width: 100%, radius: 6pt)[
    #text(size: 14pt, weight: "bold", fill: rgb("#be123c"))[2. [[FAIL_2_TITLE]]]
    #v(0.8em)
    #text(size: 12pt)[[[FAIL_2_DESC]]]
  ],
  rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), inset: 1.2cm, width: 100%, radius: 6pt)[
    #text(size: 14pt, weight: "bold", fill: rgb("#be123c"))[3. [[FAIL_3_TITLE]]]
    #v(0.8em)
    #text(size: 12pt)[[[FAIL_3_DESC]]]
  ]
)

#pagebreak()

// =========================================================
// СТРАНИЦА 4: ПЛАН ДЕЙСТВИЙ И ОФФЕР
// =========================================================
#text(size: 18pt, weight: "bold")[Дорожная карта перехвата локального спроса]
#v(0.3cm)
#text(size: 12pt)[Пошаговый план возврата первичных клиентов в кассу организации:]
#v(1cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 0.5cm,
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(weight: "bold", fill: rgb("#2563eb"))[ЭТАП 1: СТАРТ]
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[3-5 дней]
    #v(0.5em)
    #text(size: 10.5pt)[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(weight: "bold", fill: rgb("#2563eb"))[ЭТАП 2: ОЦИФРОВКА]
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[14 дней]
    #v(0.5em)
    #text(size: 10.5pt)[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(weight: "bold", fill: rgb("#2563eb"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ]
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[Постоянно]
    #v(0.5em)
    #text(size: 10.5pt)[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
  ]
)

#v(1cm)
#grid(
  columns: (1fr, 1fr),
  gutter: 1cm,
  rect(stroke: 1pt + rgb("#e2e8f0"), fill: rgb("#fff1f2"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(size: 9.5pt, weight: "bold", fill: rgb("#be123c"))[ЦЕНА НЕДЕЛИ ПРОМЕДЛЕНИЯ:]
    #v(0.5em)
    #text(size: 18pt, weight: "bold", fill: rgb("#be123c"))[[[WEEKLY_LOSS_FMT]] ₽ / нед]
    #v(0.5em)
    #text(size: 10pt)[Сумма, которая безвозвратно переходит к прямым конкурентам локации.]
  ],
  rect(stroke: 1pt + rgb("#e2e8f0"), fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 6pt)[
    #text(size: 9.5pt, weight: "bold", fill: luma(100))[БЫСТРАЯ ОКУПАЕМОСТЬ:]
    #v(0.5em)
    #text(size: 13pt, weight: "bold")[Всего 2-3 первичных визита]
    #v(0.5em)
    #text(size: 10pt)[полностью перекрывают любые затраты на профессиональную техническую оптимизацию профиля.]
  ]
)

#v(1cm)
#rect(fill: rgb("#eff6ff"), stroke: 1pt + rgb("#bfdbfe"), inset: 1.2cm, width: 100%, radius: 6pt)[
  #text(size: 15pt, weight: "bold", fill: rgb("#1d4ed8"))[Персональный 3-минутный видеоразбор]
  #v(0.8em)
  #text(size: 12pt)[
    Отправьте кодовое слово *«РАЗБОР»* в Telegram *t.me/paulvenkov* — мы бесплатно покажем на экране 3 скрытые ошибки вашей карточки и ответим на вопросы руководителя.
  ]
]

#v(1cm)
#block(breakable: false)[
  #text(size: 12pt, weight: "bold")[С уважением,]\
  #v(0.3em)
  #text(size: 11pt, fill: luma(80))[Команда аналитиков PIN100]
]

#v(0.8cm)
#text(size: 8.5pt, fill: luma(120))[
  \* По запросу (после видеоразбора) мы также готовы бесплатно предоставить готовый комплект для вашего администратора: файл правильного прейскуранта под импорт в 1 клик, шаблон продающего описания клиники и регламент подключения бесплатной онлайн-записи.
]
