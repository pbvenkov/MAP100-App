#set document(title: "Аналитическое Заключение - [[TITLE]]", author: "PIN100 Analytics")
#set page(
  paper: "a4",
  margin: (x: 20mm, y: 18mm),
  footer: context [
    #set text(size: 8pt, fill: rgb("94A3B8"))
    PIN100 Analytics | Независимый аудит поисковой гео-выдачи
    #h(1fr)
    Стр. #counter(page).display("1")
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
  Организация: #strong[[[TITLE]]] \
  Направление: #strong[[[NICHE]]] \
  Дата фиксации данных: #strong[[[DATE]]]
]
#v(35pt)
#rect(width: 100%, fill: rgb("F8FAFC"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 11pt)[
  #text(size: 8.5pt, fill: rgb("64748B"))[
    *Методология аудита:* Оценка готовности профиля к приему первичных обращений по *79 параметрам поисковой доступности*, полноты прейскуранта и простоты записи[cite: 1]. Анализ учитывает отраслевые стандарты размещения информации об услугах и квалификации специалистов.
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
      #text(size: 8pt, fill: rgb("94A3B8"), style: "italic")[Оценка по 79 факторам ранжирования]
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
    Прямо сейчас профиль скрыт от *[[DEV]]% целевых клиентов* вашего района[cite: 1]. Из-за технических недочетов в оформлении карточки вы каждый месяц отдаете конкурентам локации около *[[LOST_LEADS]] [[AUDIENCE_DECLENSION]]*[cite: 1]. \
    #v(2pt)
    *Парадокс репутации:* Высокий рейтинг подтверждает доверие постоянных клиентов[cite: 3]. Но по общим поисковым запросам алгоритмы Карт скрывают карточку от новых жителей района с острой потребностью, перенаправляя их к соседям[cite: 1, 3].
  ]
]

#v(4pt)
#text(size: 9pt, weight: "bold", fill: rgb("0A1128"))[Прозрачный расчет потерь (юнит-экономика локации):]
#v(2pt)

#set table.cell(inset: 5.5pt)
#table(
  columns: (1.3fr, 1fr, 1.4fr),
  stroke: 0.5pt + rgb("E2E8F0"),
  fill: (col, row) => if row == 0 { rgb("F1F5F9") } else if row == 5 { rgb("FFF1F2") } else { none },
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
  \* Расчет выполнен строго по первому чеку[cite: 1]. С учетом повторных визитов и прикрепления клиентов ([[CLIENT_LTV]]~мес.) совокупный отток выручки в пользу прямых конкурентов района составляет до *[[LTV_LOSS_FMT]]~₽ в год*[cite: 1].
]

#v(4pt)
#rect(width: 100%, fill: rgb("EFF6FF"), stroke: 0.5pt + rgb("BFDBFE"), radius: 3pt, inset: 7pt)[
  #text(size: 8pt, fill: rgb("1E40AF"))[
    *Важное примечание:* Оценка #strong[[[SCORE]] / 100] фиксирует исключительно техническую видимость профиля в поиске Яндекса, а не реальное высокое качество [[QUALITY_PHRASE]][cite: 1]. Это программные особенности поисковой выдачи, которые не зависят от работы администраторов.
  ]
]

#pagebreak()

// ==========================================
// СТР. 3: ТОЧКИ ПОТЕРИ ПАЦИЕНТОВ
// ==========================================
#heading(level: 2)[Три главные причины потери пациентов]
#v(4pt)
#text(size: 9pt, fill: rgb("475569"))[Почему потенциальные клиенты из вашего района уходят к конкурентам[[COMP_SAFE]][cite: 1]:]
#v(7pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[1. Разрыв между брендовыми и категорийными запросами]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[
    *Как видит пациент:* По прямому названию («[[TITLE]]») компанию найдут всегда. Однако первичные пациенты ищут не бренд, а решение проблемы: *[[SERVICE_EXAMPLE]]*[cite: 1, 3]. \
    *Что происходит в кассе:* Если в карточке нет структурированного прейскуранта с точными ценами, алгоритм исключает профиль из целевой выдачи и отдает платежеспособных клиентов карточкам с открытым прайсом[cite: 1].
  ]
]
#v(6pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[2. Барьер при попытке связаться или записаться]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[
    *Как видит пациент:* Более 60% современных пользователей на картах предпочитают мгновенную онлайн-запись или связь через мессенджер без звонка администратору вслепую. \
    *Что происходит в кассе:* Если кнопки быстрой записи нет, большинство людей закрывают карточку, не совершая звонка, и выбирают организацию, куда записаться можно в 1–2 клика[cite: 1].
  ]
]
#v(6pt)

#rect(width: 100%, fill: rgb("FFFFFF"), stroke: 0.5pt + rgb("CBD5E1"), radius: 4pt, inset: 10pt)[
  #text(size: 10pt, font: ("Playfair Display", "Georgia", "serif"), weight: "bold", fill: rgb("0A1128"))[3. Профиль выглядит «неактивным» для поисковых систем]
  #v(3pt)
  #text(size: 8.5pt, fill: rgb("475569"))[
    *Как видит поисковик:* Алгоритмы оценивают регулярность обновления карточки и обязательное наличие официальных ответов руководства на отзывы гостей[cite: 1]. \
    *Что происходит в кассе:* Отсутствие ответов на отклики и редкое обновление профиля сигнализируют системе о низкой активности[cite: 1]. Яндекс намеренно опускает такую организацию в поиске, продвигая активных соседей[cite: 1].
  ]
]

#pagebreak()

// ==========================================
// СТР. 4: ПЛАН ДЕЙСТВИЙ И СЛЕДУЮЩИЙ ШАГ
// ==========================================
#heading(level: 2)[План устранения кассового разрыва]
#v(4pt)
#text(size: 9pt, fill: rgb("475569"))[Пошаговый план возврата районного потока обращений в кассу организации[cite: 1]:]
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
    [
      #text(size: 9.5pt, weight: "bold", fill: rgb("FFFFFF"))[Получить пошаговый план исправления (ТЗ)][cite: 1] \
      #v(2pt)
      #text(size: 8pt, fill: rgb("CBD5E1"))[Напишите в Telegram — пришлем короткое 3-минутное персональное видео по вашей карточке с разбором скрытых технических ошибок профиля[cite: 1].]
    ],
    [
      #align(center + horizon)[
        #rect(fill: rgb("1E293B"), stroke: 0.5pt + rgb("8B7355"), radius: 3pt, inset: 7pt)[
          #text(size: 8pt, weight: "bold", fill: rgb("F1F5F9"))[Telegram:\ #text(fill: rgb("D97706"))[\@paulvenkov]][cite: 1]
        ]
      ]
    ]
  )
]
