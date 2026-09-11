import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

# ==========================================================
# 1. ЭКОНОМИЧЕСКИЕ ПАРАМЕТРЫ НИШ
# ==========================================================

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,
        "base_check": 5500,
        "ltv_months": 12,
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4500,
        "ltv_months": 10,
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3800,
        "ltv_months": 12,
    },
    "BEAUTY_MEDICAL": {
        "niche_name": "Медицинская косметология",
        "niche_genitive": "клиник эстетической медицины",
        "client_word": "клиент",
        "quality_phrase": "врачебной косметологии и стандартов безопасности",
        "benchmark_leads": 85,
        "base_check": 4800,
        "ltv_months": 11,
    },
    "AUTOSERVICES": {
        "niche_name": "Автосервис / Техцентр",
        "niche_genitive": "автосервисов",
        "client_word": "клиент",
        "quality_phrase": "технического обслуживания и ремонта",
        "benchmark_leads": 110,
        "base_check": 7500,
        "ltv_months": 8,
    },
    "OTHER": {
        "niche_name": "Организация сферы услуг",
        "niche_genitive": "организаций",
        "client_word": "клиент",
        "quality_phrase": "стандартов сервиса и качества обслуживания",
        "benchmark_leads": 80,
        "base_check": 4000,
        "ltv_months": 9,
    },
}

# ==========================================================
# 2. ИНТЕГРАЦИЯ С DADATA И ПАРСЕР ССЫЛОК ЯНДЕКС КАРТ
# ==========================================================

def parse_yandex_maps_url(url: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Распознает ссылку любого формата (включая короткие редиректы yandex.ru/maps/-/).
    Возвращает: (org_id, slug_name, canonical_url).
    """
    raw_url = url.strip()
    if not raw_url:
        return None, None, raw_url

    canonical = raw_url
    # Раскрываем короткие ссылки через HEAD-запрос
    if "/maps/-/" in raw_url or "clck.ru" in raw_url or "bit.ly" in raw_url:
        try:
            resp = requests.head(raw_url, allow_redirects=True, timeout=4)
            canonical = resp.url
        except Exception:
            pass

    org_id = None
    slug_name = None

    # 1. Шаблон вида /org/[slug]/[id] или /org/[id]
    m_org = re.search(r'/org/(?:([^/?#]+)/)?(\d+)', canonical)
    if m_org:
        slug = m_org.group(1)
        org_id = m_org.group(2)
        if slug and not slug.isdigit():
            slug_name = urllib.parse.unquote(slug).replace('_', ' ').replace('-', ' ').title()

    # 2. Параметр ?oid=[id]
    if not org_id:
        m_oid = re.search(r'[?&]oid=(\d+)', canonical)
        if m_oid:
            org_id = m_oid.group(1)

    # 3. Шаблон /objects/[id]
    if not org_id:
        m_obj = re.search(r'/objects/(\d+)', canonical)
        if m_obj:
            org_id = m_obj.group(1)

    return org_id, slug_name, canonical


def fetch_dadata_parties(query: str, token: str) -> List[Dict[str, Any]]:
    """Поиск организаций по названию или ИНН через DaData Suggestions API."""
    if not query.strip() or not token.strip():
        return []

    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
    headers = {
        "Authorization": f"Token {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"query": query.strip(), "count": 7}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=4)
        if r.status_code == 200:
            return r.json().get("suggestions", [])
    except Exception:
        pass
    return []


def make_yandex_search_url(company_name: str, address: str = "") -> str:
    """Генерирует поисковую ссылку на Яндекс Карты по названию и адресу."""
    text_query = f"{company_name} {address}".strip()
    return f"https://yandex.ru/maps/?text={urllib.parse.quote_plus(text_query)}"

# ==========================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
# ==========================================================

def format_currency(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def get_declension(number: int, word_type: str = "пациент") -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type == "пациент":
        if 11 <= n <= 19:
            return "пациентов"
        if n1 == 1:
            return "пациент"
        if 2 <= n1 <= 4:
            return "пациента"
        return "пациентов"
    if word_type == "клиент":
        if 11 <= n <= 19:
            return "клиентов"
        if n1 == 1:
            return "клиент"
        if 2 <= n1 <= 4:
            return "клиента"
        return "клиентов"
    return "обращений"


def get_score_color(score: float) -> str:
    if score >= 80:
        return "16a34a"
    if score >= 60:
        return "d97706"
    return "dc2626"


def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")
    return clean if clean else "report"

# ==========================================================
# 4. ГЕНЕРАТОР ПЕРВОГО СООБЩЕНИЯ (ICEBREAKER)
# ==========================================================

def generate_icebreaker(
    title: str,
    rating: float | str,
    competitors: List[str],
    lost_leads: int,
    niche_genitive: str = "стоматологий",
) -> str:
    if competitors and len(competitors) >= 2:
        comp_str = f"«{competitors[0]}» и «{competitors[1]}»"
    elif competitors and len(competitors) == 1:
        comp_str = f"«{competitors[0]}»"
    else:
        comp_str = "прямые конкуренты локации"

    low_range = max(1, lost_leads - 2)
    high_range = lost_leads + 3
    leads_range_str = f"{low_range}–{high_range}"

    return (
        f"Добрый день!\n\n"
        f"Анализировали выдачу {niche_genitive} в вашем районе на Яндекс Картах "
        f"и обратили внимание на карточку «{title}». При сильной репутации ({rating}) "
        f"первичный поток прямо сейчас перехватывают {comp_str}.\n\n"
        f"На поверхности лежит отсутствие кнопки быстрой записи (пациенты вечером не хотят звонить "
        f"и уходят к соседям), но алгоритмы пессимизируют карточку еще по нескольким (иногда не очевидным) "
        f"параметрам. По емкости района это отток около {leads_range_str} пациентов в месяц.\n\n"
        f"Собрали наглядный разбор карточки и расчет потерь в короткий PDF на 4 страницы. "
        f"Скинуть файл сюда для ознакомления?"
    )

# ==========================================================
# 5. РАСЧЕТ ЮНИТ-ЭКОНОМИКИ
# ==========================================================

def calculate_report_metrics(audit_data: Dict[str, Any]) -> Dict[str, str]:
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_info = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])

    title = audit_data.get("title", "Организация")
    rating = audit_data.get("rating", 4.7)
    score = min(100.0, max(0.0, float(audit_data.get("score", 66.5))))

    leads_bench = audit_data.get("benchmark_leads", niche_info["benchmark_leads"])
    base_check = audit_data.get("base_check", niche_info["base_check"])
    ltv_months = audit_data.get("ltv_months", niche_info["ltv_months"])

    dev = max(0.0, round(100.0 - score, 1))
    lost_leads = int(round(leads_bench * (dev / 100.0)))
    rev_loss = lost_leads * base_check
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * ltv_months

    word_type = niche_info["client_word"]
    table_declension = get_declension(lost_leads, word_type)

    failures = audit_data.get("top_failures", [])
    while len(failures) < 3:
        failures.append({
            "title": "Техническая оптимизация карточки",
            "desc": "Параметры карточки требуют настройки для удержания позиций в районе."
        })

    report_date = audit_data.get("date", datetime.date.today().strftime("%d.%m.%Y"))

    return {
        "[[TITLE]]": title,
        "[[NICHE]]": niche_info["niche_name"],
        "[[DATE]]": report_date,
        "[[SCORE]]": f"{score:.1f}" if score % 1 != 0 else str(int(score)),
        "[[SCORE_COLOR]]": get_score_color(score),
        "[[REV_LOSS_FMT]]": format_currency(rev_loss),
        "[[CLIENT_LEADS]]": str(leads_bench),
        "[[DEV]]": f"{dev:.1f}" if dev % 1 != 0 else str(int(dev)),
        "[[LOST_LEADS]]": str(lost_leads),
        "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": format_currency(base_check),
        "[[CLIENT_LTV]]": str(ltv_months),
        "[[LTV_LOSS_FMT]]": format_currency(ltv_loss),
        "[[QUALITY_PHRASE]]": niche_info["quality_phrase"],
        "[[EXECUTIVE_SUMMARY]]": audit_data.get(
            "executive_summary",
            f"Профиль «{title}» обладает высокой клинической репутацией ({rating}), однако из-за отсутствия прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм перенаправляет до {lost_leads} готовых обращений в месяц прямым конкурентам локации."
        ),
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери пациентов",
        "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": failures[0]["title"],
        "[[FAIL_1_DESC]]": failures[0]["desc"],
        "[[FAIL_2_TITLE]]": failures[1]["title"],
        "[[FAIL_2_DESC]]": failures[1]["desc"],
        "[[FAIL_3_TITLE]]": failures[2]["title"],
        "[[FAIL_3_DESC]]": failures[2]["desc"],
        "[[WEEKLY_LOSS_FMT]]": format_currency(weekly_loss),
    }

# ==========================================================
# 6. КОМПИЛЯТОР TYPST
# ==========================================================

def render_typst_template(template_path: Path, mapping: Dict[str, str]) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    for placeholder, val in mapping.items():
        content = content.replace(placeholder, str(val))
    return content


def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> Tuple[bool, str]:
    temp_typ_path = work_dir / f"temp_{output_pdf_path.stem}.typ"
    try:
        with open(temp_typ_path, "w", encoding="utf-8") as f:
            f.write(typst_content)
        cmd = ["typst", "compile", str(temp_typ_path), str(output_pdf_path)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, f"Ошибка компиляции Typst: {e.stderr}"
    except FileNotFoundError:
        return False, "Утилита 'typst' CLI не установлена в PATH."
    finally:
        if temp_typ_path.exists():
            try:
                temp_typ_path.unlink()
            except OSError:
                pass

# ==========================================================
# 7. ИНТЕРФЕЙС STREAMLIT
# ==========================================================

def apply_json_payload(data: Dict[str, Any]) -> None:
    st.session_state["f_title"] = data.get("title", "")
    st.session_state["f_org_id"] = str(data.get("org_id", ""))
    st.session_state["f_rating"] = float(data.get("rating", 4.7))
    st.session_state["f_score"] = float(data.get("score", 66.5))
    
    niche = data.get("niche", "DENTISTRY")
    if niche in NICHE_CONFIG:
        st.session_state["f_niche"] = niche

    comps = data.get("competitors", [])
    st.session_state["f_comp1"] = comps[0] if len(comps) > 0 else ""
    st.session_state["f_comp2"] = comps[1] if len(comps) > 1 else ""

    if "benchmark_leads" in data:
        st.session_state["f_bench"] = int(data["benchmark_leads"])
    if "base_check" in data:
        st.session_state["f_check"] = int(data["base_check"])
    if "ltv_months" in data:
        st.session_state["f_ltv"] = int(data["ltv_months"])

    fails = data.get("top_failures", [])
    if len(fails) > 0:
        st.session_state["f_f1_t"] = fails[0].get("title", "")
        st.session_state["f_f1_d"] = fails[0].get("desc", "")
    if len(fails) > 1:
        st.session_state["f_f2_t"] = fails[1].get("title", "")
        st.session_state["f_f2_d"] = fails[1].get("desc", "")
    if len(fails) > 2:
        st.session_state["f_f3_t"] = fails[2].get("title", "")
        st.session_state["f_f3_d"] = fails[2].get("desc", "")


def run_streamlit_app() -> None:
    st.set_page_config(
        page_title="PIN100 Analytics",
        page_icon="📍",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    DEFAULT_FAILURES = [
        {
            "title": "Отсутствие кнопки быстрой онлайн-записи (модуля МИС)",
            "desc": "Пациенты в вечерние часы и с мобильных устройств не могут записаться в один клик. Без прямого действия свыше 60% вечернего спроса возвращаются в выдачу и уходят к конкурентам."
        },
        {
            "title": "Отсутствие витрины специалистов в профиле",
            "desc": "В карточке не оцифрованы профили врачей (фотографии, стаж, специализации). В медицине ключевое решение пациент принимает «на врача»: карточка проигрывает конкурентам с открытой командой."
        },
        {
            "title": "Фрагментарный прейскурант без цен формата «от...»",
            "desc": "В карточке заполнено менее трети ключевых позиций (имплантация, терапия, гигиена). Поисковые алгоритмы Яндекса пессимизируют профиль по предметным запросам процедур."
        }
    ]

    with st.sidebar:
        st.header("1. Быстрый импорт данных")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("🔄 Тест: Айдента", use_container_width=True):
                st.session_state["f_title"] = "Айдента"
                st.session_state["f_org_id"] = "1015646715"
                st.session_state["f_yandex_url"] = "https://yandex.ru/maps/org/aidenta/1015646715/"
                st.session_state["f_rating"] = 4.7
                st.session_state["f_score"] = 66.5
                st.session_state["f_niche"] = "DENTISTRY"
                st.session_state["f_comp1"] = "РозДент"
                st.session_state["f_comp2"] = "На Приморской"
                st.rerun()

        with col_b2:
            if st.button("➕ Очистить", use_container_width=True):
                for k in ["f_title", "f_org_id", "f_yandex_url", "f_comp1", "f_comp2"]:
                    st.session_state[k] = ""
                st.session_state["f_rating"] = 4.8
                st.session_state["f_score"] = 70.0
                st.rerun()

        # СПОСОБЫ ВВОДА ОРГАНИЗАЦИИ
        input_mode = st.radio(
            "Способ поиска / добавления:",
            ["🔗 По ссылке на Карты", "🏢 Поиск через DaData", "📂 Загрузить JSON", "✍️ Ручной ввод"],
            index=0
        )

        # 1. Парсинг ссылки на Яндекс Карты
        if input_mode == "🔗 По ссылке на Карты":
            input_url = st.text_input(
                "Вставьте ссылку на карточку в Картах:",
                value=st.session_state.get("f_yandex_url", ""),
                placeholder="https://yandex.ru/maps/org/... или https://yandex.ru/maps/-/... "
            )
            if st.button("🔍 Распознать ссылку", use_container_width=True):
                if input_url.strip():
                    oid, slug_name, canon = parse_yandex_maps_url(input_url)
                    st.session_state["f_yandex_url"] = canon
                    if oid:
                        st.session_state["f_org_id"] = oid
                        st.success(f"Распознан ID организации: {oid}")
                    if slug_name and not st.session_state.get("f_title"):
                        st.session_state["f_title"] = slug_name
                    st.rerun()

        # 2. Поиск через DaData
        elif input_mode == "🏢 Поиск через DaData":
            dadata_token = st.text_input(
                "API-ключ DaData:",
                value=st.session_state.get("dadata_key", os.getenv("DADATA_API_KEY", "")),
                type="password",
                help="Бесплатный токен на dadata.ru"
            )
            if dadata_token:
                st.session_state["dadata_key"] = dadata_token

            query_party = st.text_input("Название компании или ИНН:", placeholder="Например: Айдента или 7701234567")

            if query_party.strip() and dadata_token:
                suggestions = fetch_dadata_parties(query_party, dadata_token)
                if suggestions:
                    options_dict = {}
                    for s in suggestions:
                        name = s.get("value", "")
                        addr = s.get("data", {}).get("address", {}).get("value", "")
                        inn = s.get("data", {}).get("inn", "")
                        label = f"{name} (ИНН: {inn}, {addr[:40]}...)"
                        options_dict[label] = s

                    selected_label = st.selectbox("Выберите организацию из базы:", options=list(options_dict.keys()))
                    if st.button("Применить выбранную компанию", use_container_width=True):
                        chosen = options_dict[selected_label]
                        comp_name = chosen.get("data", {}).get("name", {}).get("short_with_opf") or chosen.get("value", "")
                        comp_addr = chosen.get("data", {}).get("address", {}).get("value", "")
                        
                        st.session_state["f_title"] = comp_name
                        maps_link = make_yandex_search_url(comp_name, comp_addr)
                        st.session_state["f_yandex_url"] = maps_link
                        st.success(f"Подставлена организация: {comp_name}")
                        st.rerun()
                else:
                    st.caption("Организаций не найдено.")
            elif not dadata_token:
                st.info("Укажите API-ключ DaData для активации поиска.")

        # 3. Импорт JSON
        elif input_mode == "📂 Загрузить JSON":
            uploaded_json = st.file_uploader("Загрузите .json файл аудита", type=["json"])
            if uploaded_json is not None:
                try:
                    payload = json.load(uploaded_json)
                    apply_json_payload(payload)
                    st.success("JSON данные успешно применены!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка JSON: {e}")

        st.divider()

        # ОСНОВНЫЕ ПОЛЯ КАРТОЧКИ
        st.header("2. Параметры карточки")
        title = st.text_input(
            "Название компании / клиники",
            value=st.session_state.get("f_title", "Айдента"),
            placeholder="Например: Дентал Люкс"
        )
        org_id = st.text_input(
            "ID в Яндекс Бизнесе",
            value=st.session_state.get("f_org_id", "1015646715"),
            placeholder="Например: 1015646715"
        )
        
        yandex_url = st.text_input(
            "Ссылка на карточку в Картах",
            value=st.session_state.get("f_yandex_url", "https://yandex.ru/maps/org/aidenta/1015646715/"),
            placeholder="https://yandex.ru/maps/org/..."
        )

        niche_list = list(NICHE_CONFIG.keys())
        saved_niche = st.session_state.get("f_niche", "DENTISTRY")
        niche_idx = niche_list.index(saved_niche) if saved_niche in niche_list else 0
        niche_key = st.selectbox(
            "Сфера бизнеса",
            options=niche_list,
            index=niche_idx,
            format_func=lambda x: NICHE_CONFIG[x]["niche_name"]
        )

        rating = st.number_input(
            "Рейтинг на Картах",
            min_value=1.0,
            max_value=5.0,
            value=float(st.session_state.get("f_rating", 4.7)),
            step=0.1
        )
        score = st.slider(
            "Балл готовности профиля (из 100)",
            min_value=10.0,
            max_value=98.0,
            value=float(st.session_state.get("f_score", 66.5)),
            step=0.5
        )

        st.header("3. Конкуренты локации")
        comp_1 = st.text_input("Конкурент №1", value=st.session_state.get("f_comp1", "РозДент"))
        comp_2 = st.text_input("Конкурент №2", value=st.session_state.get("f_comp2", "На Приморской"))

        st.header("4. Экономика ниши")
        n_def = NICHE_CONFIG[niche_key]
        leads_bench = st.number_input(
            "Медиана ТОП-3 (обращений/мес)",
            value=int(st.session_state.get("f_bench", n_def["benchmark_leads"])),
            step=5
        )
        base_check = st.number_input(
            "Базовый чек визита (₽)",
            value=int(st.session_state.get("f_check", n_def["base_check"])),
            step=500
        )
        ltv_months = st.number_input(
            "Горизонт LTV (мес)",
            value=int(st.session_state.get("f_ltv", n_def["ltv_months"])),
            step=1
        )

    # Главный экран
    st.title("📍 PIN100 Analytics: Генератор аудитов гео-выдачи")
    st.caption("Расчет утечки первичных клиентов к конкурентам локации, формирование 4-страничного PDF и сообщения для ЛПР.")

    col_left, col_right = st.columns([1.1, 0.9])

    with col_left:
        st.subheader("Барьеры карточки (Стр. 3 отчета)")
        st.caption("Причины потери клиентов, которые попадут в аналитическое заключение:")

        f1_t = st.text_input("Барьер 1: Заголовок", value=st.session_state.get("f_f1_t", DEFAULT_FAILURES[0]["title"]))
        f1_d = st.text_area("Барьер 1: Пояснение", value=st.session_state.get("f_f1_d", DEFAULT_FAILURES[0]["desc"]), height=70)

        f2_t = st.text_input("Барьер 2: Заголовок", value=st.session_state.get("f_f2_t", DEFAULT_FAILURES[1]["title"]))
        f2_d = st.text_area("Барьер 2: Пояснение", value=st.session_state.get("f_f2_d", DEFAULT_FAILURES[1]["desc"]), height=70)

        f3_t = st.text_input("Барьер 3: Заголовок", value=st.session_state.get("f_f3_t", DEFAULT_FAILURES[2]["title"]))
        f3_d = st.text_area("Барьер 3: Пояснение", value=st.session_state.get("f_f3_d", DEFAULT_FAILURES[2]["desc"]), height=70)

    display_title = title.strip() if title.strip() else "Ваша клиника"
    competitors = [c.strip() for c in [comp_1, comp_2] if c.strip()]
    if not competitors:
        competitors = ["ближайшие конкуренты района"]

    audit_payload = {
        "title": display_title,
        "org_id": org_id.strip() if org_id.strip() else "0000000000",
        "date": datetime.date.today().strftime("%d.%m.%Y"),
        "date_raw": datetime.date.today().strftime("%Y-%m-%d"),
        "rating": rating,
        "score": score,
        "niche": niche_key,
        "competitors": competitors,
        "benchmark_leads": leads_bench,
        "base_check": base_check,
        "ltv_months": ltv_months,
        "top_failures": [
            {"title": f1_t, "desc": f1_d},
            {"title": f2_t, "desc": f2_d},
            {"title": f3_t, "desc": f3_d},
        ]
    }

    mapping = calculate_report_metrics(audit_payload)

    with col_right:
        st.subheader("Экономические показатели")
        m1, m2 = st.columns(2)
        m1.metric("Оценка карточки", f"{mapping['[[SCORE]]']} / 100")
        m2.metric("Потери пациентов", f"~{mapping['[[LOST_LEADS]]']} чел/мес")

        m3, m4 = st.columns(2)
        m3.metric("Упущенная выручка", f"{mapping['[[REV_LOSS_FMT]]']} ₽/мес")
        m4.metric("Потери за неделю", f"~{mapping['[[WEEKLY_LOSS_FMT]]']} ₽/нед")

        if yandex_url:
            st.markdown(f"🔗 **Карточка в Яндекс Картах:** [Открыть профиль]({yandex_url})")

        st.divider()

        st.subheader("Первое сообщение руководителю (Icebreaker)")
        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        icebreaker_txt = generate_icebreaker(
            title=display_title,
            rating=rating,
            competitors=competitors,
            lost_leads=lost_leads_int,
            niche_genitive=n_def["niche_genitive"]
        )

        st.text_area("Текст для WhatsApp / Telegram / Email", value=icebreaker_txt, height=190)

    st.divider()

    # Генерация PDF
    st.subheader("Генерация PDF-отчета")
    template_file = Path("report_template.typ")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    file_prefix = f"{sanitize_filename(display_title)}_{audit_payload['org_id']}_{audit_payload['date_raw']}"
    pdf_path = output_dir / f"{file_prefix}_report.pdf"

    if not template_file.exists():
        st.error(f"Файл шаблона '{template_file}' не найден рядом с app.py.")
    else:
        btn_col1, btn_col2 = st.columns([1.5, 2.5])
        with btn_col1:
            if st.button("🚀 Скомпилировать PDF-отчет", type="primary", use_container_width=True):
                rendered_typst = render_typst_template(template_file, mapping)
                ok, err = compile_typst_pdf(rendered_typst, pdf_path, output_dir)
                if ok:
                    st.success(f"Отчет успешно собран: {pdf_path.name}")
                    st.session_state["last_pdf"] = str(pdf_path)
                else:
                    st.warning(f"{err}")
                    st.session_state["last_typ"] = rendered_typst

        with btn_col2:
            if "last_pdf" in st.session_state and Path(st.session_state["last_pdf"]).exists():
                with open(st.session_state["last_pdf"], "rb") as f:
                    st.download_button(
                        label="📥 Скачать готовый PDF файл",
                        data=f.read(),
                        file_name=Path(st.session_state["last_pdf"]).name,
                        mime="application/pdf",
                        use_container_width=True
                    )
            elif "last_typ" in st.session_state:
                st.download_button(
                    label="📥 Скачать разметку .typ (для Typst CLI)",
                    data=st.session_state["last_typ"],
                    file_name=f"{file_prefix}.typ",
                    mime="text/plain",
                    use_container_width=True
                )

# ==========================================================
# 8. ТОЧКА ВХОДА CLI
# ==========================================================

def run_cli_mode() -> None:
    parser = argparse.ArgumentParser(description="PIN100 Analytics CLI")
    parser.add_argument("-f", "--file", type=str, help="Путь к входному JSON файлу.")
    parser.add_argument("-t", "--template", type=str, default="report_template.typ", help="Путь к шаблону Typst.")
    parser.add_argument("-o", "--outdir", type=str, default="output", help="Папка вывода.")
    parser.add_argument("--sample", action="store_true", help="Запустить тест для Айденты.")
    parser.add_argument("--cli", action="store_true", help="Запуск в режиме командной строки.")

    args, _ = parser.parse_known_args()
    template_file = Path(args.template)
    out_dir = Path(args.outdir)
    out_dir.mkdir(exist_ok=True)

    if args.sample or not args.file:
        sample = {
            "title": "Айдента",
            "org_id": "1015646715",
            "date": datetime.date.today().strftime("%d.%m.%Y"),
            "date_raw": datetime.date.today().strftime("%Y-%m-%d"),
            "rating": 4.7,
            "score": 66.5,
            "niche": "DENTISTRY",
            "competitors": ["РозДент", "На Приморской"],
            "benchmark_leads": 70,
            "base_check": 5500,
            "ltv_months": 12,
        }
        mapping = calculate_report_metrics(sample)
        if template_file.exists():
            rendered = render_typst_template(template_file, mapping)
            pdf_path = out_dir / "Айдента_report.pdf"
            compile_typst_pdf(rendered, pdf_path, out_dir)
            print(f"[+] PDF сохранен в: {pdf_path}")
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else [data]
        for item in items:
            mapping = calculate_report_metrics(item)
            if template_file.exists():
                rendered = render_typst_template(template_file, mapping)
                pdf_p = out_dir / f"{sanitize_filename(item.get('title', 'org'))}_report.pdf"
                compile_typst_pdf(rendered, pdf_p, out_dir)
                print(f"[+] Обработана клиника: {item.get('title')}")


if __name__ == "__main__":
    if "--cli" in sys.argv or "-f" in sys.argv or "--sample" in sys.argv:
        run_cli_mode()
    else:
        run_streamlit_app()
