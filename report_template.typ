#set page(
  paper: "a4",
  margin: (x: 2cm, y: 2cm),
  header: [
    #set text(8pt, fill: luma(120))
    #grid(
      columns: (1fr, 1fr),
      align(left)[PIN100 Analytics | Независимый аудит поисковой гео-выдачи],
      align(right)[Стр. #context counter(page).display()]
    )
    #v(0.5cm)
    #line(length: 100%, stroke: 0.5pt + luma(200))
  ],
  footer: []
)

#set text(font: "Arial", size: 10pt, lang: "ru")

// СТРАНИЦА 1: ТИТУЛЬНЫЙ ЛИСТ
#text(size: 24pt, weight: "bold", fill: rgb("#e11d48"))[PIN100 ANALYTICS]
#v(0.5cm)
#text(size: 16pt, weight: "bold")[Аналитическое заключение:\nГде профиль теряет первичных клиентов]
#v(0.2cm)
#text(size: 12pt, fill: luma(80))[Расчет упущенной выручки локации и перетока спроса к конкурентам]

#v(2cm)
#rect(fill: rgb("#f8fafc"), stroke: 1pt + rgb("#e2e8f0"), radius: 4pt, inset: 1cm, width: 100%)[
  #grid(
    columns: (1fr, 2fr),
    row-gutter: 1em,
    text(weight: "bold")[Организация:], text(weight: "bold", size: 12pt)[[[TITLE]]],
    text(weight: "bold")[Направление:], [[[NICHE]]],
    text(weight: "bold")[Дата фиксации данных:], [[[DATE]]]
  )
]

#v(2cm)
#text(size: 14pt, weight: "bold")[Практическая ценность для руководителя:]
#v(0.5cm)
#text(size: 11pt)[
  Отчет показывает скрытые программные фильтры Яндекс Карт, из-за которых готовые к обращению клиенты района уходят к ближайшим конкурентам. Здесь нет общих советов по рекламе: зафиксированы конкретные барьеры конверсии в профиле и рассчитана упущенная выручка бизнеса без затрат на платный трафик.
]

#pagebreak()

// СТРАНИЦА 2: РЕЗЮМЕ
#text(size: 18pt, weight: "bold")[Резюме для руководителя]
#v(1cm)

#grid(
  columns: (1fr, 1fr),
  gutter: 1cm,
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(size: 10pt, fill: luma(100), transform: "uppercase")[Готовность карточки к приему трафика]
    #v(0.5em)
    #text(size: 24pt, weight: "bold", fill: rgb("#[[SCORE_COLOR]]"))[[[SCORE]]/100]
    #v(0.5em)
    #text(size: 9pt, fill: luma(80))[Оценка факторов конверсии и ранжирования]
  ],
  rect(fill: rgb("#fff1f2"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(size: 10pt, fill: rgb("#e11d48"), transform: "uppercase")[Прямые потери выручки]
    #v(0.5em)
    #text(size: 24pt, weight: "bold", fill: rgb("#e11d48"))[[[REV_LOSS_FMT]] ₽/мес]
    #v(0.5em)
    #text(size: 9pt, fill: luma(80))[Консервативная оценка первого визита]
  ]
)

#v(1cm)
#text(size: 14pt, weight: "bold")[Парадокс локального поиска: почему высокого рейтинга больше недостаточно]
#v(0.5em)
Более 65% людей выбирают организацию в мобильных Картах за 40-60 секунд, не переходя на сайт (модель Zero-Click). Высокий рейтинг создает первичное доверие, но современные алгоритмы выдачи отдают верхние позиции карточкам с активным функционалом: мгновенная онлайн-запись, оцифрованный прайс и прямой чат. Карточка без этих инструментов теряет горячих клиентов еще до звонка администратору.

#v(1cm)
#rect(stroke: (left: 4pt + rgb("#e11d48")), fill: rgb("#fafafa"), inset: 1em, width: 100%)[
  #text(weight: "bold")[Критический вывод анализа:]\
  #v(0.5em)
  [[EXECUTIVE_SUMMARY]]
]

#v(1cm)
#text(size: 14pt, weight: "bold")[Воронка потерь: где именно карточка теряет клиентов]
#v(0.5em)
#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 0.5cm,
  rect(fill: rgb("#f8fafc"), inset: 10pt, width: 100%)[
    #text(weight: "bold", size: 10pt)[1. ТРАФИК ЛИДЕРОВ РАЙОНА]\
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#3b82f6"))[[[CLIENT_LEADS]] обр./мес]\
    #v(0.5em)
    #text(size: 9pt)[Медиана прямых контактов: звонки, маршруты и онлайн-запись в ТОП-3 локации.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 10pt, width: 100%)[
    #text(weight: "bold", size: 10pt)[2. ЭКРАННЫЙ ФИЛЬТР]\
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#d97706"))[Отказ от звонка]\
    #v(0.5em)
    #text(size: 9pt)[65% людей не звонят, если нет онлайн-записи или не виден понятный прайс.]
  ],
  rect(fill: rgb("#fff1f2"), inset: 10pt, width: 100%)[
    #text(weight: "bold", size: 10pt)[3. УХОД К СОСЕДЯМ]\
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#e11d48"))[-[[REV_LOSS_FMT]] ₽/мес]\
    #v(0.5em)
    #text(size: 9pt)[[[LOST_LEADS]] [[TABLE_DECLENSION]] ежемесячно перетекают в активные карточки района.]
  ]
)

#v(0.5cm)
#text(size: 8pt, fill: luma(120))[
  \* Консервативный расчет первого визита (базовый чек [[CLIENT_CHECK_FMT]] ₽). С учетом повторных визитов и прикрепления клиентов годовой отток районного бюджета составляет до [[LTV_LOSS_FMT]] ₽. Источник бенчмарков: [[BENCHMARK_SOURCE]].\
  \
  Важное примечание: Оценка [[SCORE]] / 100 фиксирует исключительно техническую готовность профиля в гео-выдаче Яндекса, а не реальное качество [[QUALITY_PHRASE]]. Это программные особенности поисковой системы, которые не зависят от работы администраторов и специалистов.
]

#pagebreak()

// СТРАНИЦА 3: ТОП ОШИБОК
#text(size: 18pt, weight: "bold")[[[PAGE_3_HEADING]]]
#v(0.5cm)
#text(size: 11pt)[[[PAGE_3_SUBTITLE]]]
#v(1cm)

#grid(
  columns: (1fr),
  row-gutter: 1.5cm,
  [
    #text(size: 14pt, weight: "bold", fill: rgb("#e11d48"))[1. [[FAIL_1_TITLE]]]
    #v(0.5em)
    #text(size: 11pt)[[[FAIL_1_DESC]]]
  ],
  [
    #text(size: 14pt, weight: "bold", fill: rgb("#e11d48"))[2. [[FAIL_2_TITLE]]]
    #v(0.5em)
    #text(size: 11pt)[[[FAIL_2_DESC]]]
  ],
  [
    #text(size: 14pt, weight: "bold", fill: rgb("#e11d48"))[3. [[FAIL_3_TITLE]]]
    #v(0.5em)
    #text(size: 11pt)[[[FAIL_3_DESC]]]
  ]
)

#pagebreak()

// СТРАНИЦА 4: ПЛАН ДЕЙСТВИЙ
#text(size: 18pt, weight: "bold")[Дорожная карта перехвата локального спроса]
#v(0.5cm)
#text(size: 11pt)[Пошаговый план возврата первичных клиентов в кассу организации:]
#v(1cm)

#grid(
  columns: (1fr, 1fr, 1fr),
  gutter: 0.5cm,
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", fill: rgb("#3b82f6"))[ЭТАП 1: СТАРТ]\
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[3-5 дней]\
    #v(0.5em)
    #text(size: 10pt)[Привязка услуг к частым запросам пациентов, исправление меток входа, парковки и дублирующих адресов.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", fill: rgb("#3b82f6"))[ЭТАП 2: ОЦИФРОВКА]\
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[14 дней]\
    #v(0.5em)
    #text(size: 10pt)[Подключение быстрой онлайн-записи, оформление карточек специалистов с опытом и фото, наглядный прейскурант.]
  ],
  rect(fill: rgb("#f8fafc"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(weight: "bold", fill: rgb("#3b82f6"))[ЭТАП 3: ЗАКРЕПЛЕНИЕ]\
    #v(0.3em)
    #text(size: 9pt, weight: "bold")[Постоянно]\
    #v(0.5em)
    #text(size: 10pt)[Регламент ответов на отзывы пациентов, защита профиля от недостоверных правок, удержание в ТОП-3 района.]
  ]
)

#v(1cm)
#grid(
  columns: (1fr, 1fr),
  gutter: 1cm,
  rect(stroke: 1pt + rgb("#e2e8f0"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(size: 10pt, fill: luma(100))[ЦЕНА НЕДЕЛИ ПРОМЕДЛЕНИЯ:]
    #v(0.5em)
    #text(size: 16pt, weight: "bold", fill: rgb("#e11d48"))[[[WEEKLY_LOSS_FMT]] ₽ / нед]
    #v(0.5em)
    #text(size: 9pt)[Сумма, которая безвозвратно переходит к прямым конкурентам локации.]
  ],
  rect(stroke: 1pt + rgb("#e2e8f0"), inset: 15pt, width: 100%, radius: 4pt)[
    #text(size: 10pt, fill: luma(100))[БЫСТРАЯ ОКУПАЕМОСТЬ:]
    #v(0.5em)
    #text(size: 11pt, weight: "bold")[Всего 2-3 первичных визита]
    #v(0.5em)
    #text(size: 9pt)[полностью перекрывают любые затраты на техническую оптимизацию профиля.]
  ]
)

#v(1.5cm)
#rect(fill: rgb("#eff6ff"), inset: 15pt, width: 100%, radius: 4pt)[
  #text(size: 14pt, weight: "bold", fill: rgb("#1d4ed8"))[Персональный 3-минутный видеоразбор]
  #v(0.5em)
  #text(size: 11pt)[
    Отправьте слово *«РАЗБОР»* в Telegram *@paulvenkov* — мы покажем на экране 3 скрытые ошибки вашей карточки и ответим на вопросы руководителя.
  ]
]

#v(1cm)
#text(size: 8pt, fill: luma(120))[
  \* По запросу также предоставим готовый комплект для администратора (файл прейскуранта под импорт в 1 клик, продающее описание и регламент подключения онлайн-записи).
]
