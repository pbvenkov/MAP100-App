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
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================================================
# 1. ID ПАПОК GOOGLE DRIVE И НАСТРОЙКИ НИШ
# ==========================================================

GDRIVE_FOLDERS = {
    "JSON": "1efm3iHSVvUPp50in3tfOGxd0xOACio2E",
    "PDF": "15kzKEaS76HAhx22FR-BTvifbaecH_wx8",
    "LETTERS": "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6",
}

GDRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

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
# 2. МОДУЛЬ GOOGLE DRIVE И GOOGLE SHEETS
# ==========================================================

def get_google_credentials() -> Optional[service_account.Credentials]:
    """Загружает учетные данные Google Service Account из файла или st.secrets."""
    key_paths = ["credentials.json", "service_account.json"]
    for path_str in key_paths:
        p = Path(path_str)
        if p.exists():
            return service_account.Credentials.from_service_account_file(
                str(p), scopes=GDRIVE_SCOPES
            )

    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        return service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=GDRIVE_SCOPES
        )
    return None


def get_or_create_date_folder(drive_service: Any, parent_folder_id: str, date_str: str) -> str:
    """Ищет папку с датой внутри родительской папки; если нет — создает ее."""
    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{date_str}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": date_str,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_file_to_drive(
    drive_service: Any,
    local_file_path: Path,
    target_folder_id: str,
    mime_type: str
) -> Dict[str, str]:
    """Загружает локальный файл в указанную папку Google Drive."""
    metadata = {
        "name": local_file_path.name,
        "parents": [target_folder_id],
    }
    media = MediaFileUpload(str(local_file_path), mimetype=mime_type, resumable=True)
    uploaded = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink"
    ).execute()
    return {
        "id": uploaded.get("id", ""),
        "link": uploaded.get("webViewLink", "")
    }


def append_row_to_google_sheet(
    sheets_service: Any,
    spreadsheet_id: str,
    row_values: List[Any],
    sheet_range: str = "Лист1!A:L"
) -> bool:
    """Дописывает строку с результатами аудита в Google Таблицу."""
    try:
        body = {"values": [row_values]}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        return True
    except Exception as e:
        st.warning(f"Ошибка записи в Google Таблицу: {e}")
        return False


def sync_results_to_google(
    audit_data: Dict[str, Any],
    mapping: Dict[str, str],
    pdf_path: Path,
    txt_path: Path,
    json_path: Path,
    spreadsheet_id: Optional[str] = None
) -> Dict[str, str]:
    """Выполняет выгрузку PDF, TXT и JSON в подпапки с датой и логирует строку в Таблицу."""
    creds = get_google_credentials()
    if not creds:
        raise FileNotFoundError(
            "Файл ключа сервисного аккаунта Google (credentials.json или service_account.json) не найден в корне проекта."
        )

    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    date_folder_name = datetime.date.today().strftime("%Y-%m-%d")
    links = {}

    # 1. Загрузка PDF в папку PDF/YYYY-MM-DD
    target_pdf_dir = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["PDF"], date_folder_name)
    pdf_res = upload_file_to_drive(drive_service, pdf_path, target_pdf_dir, "application/pdf")
    links["pdf"] = pdf_res["link"]

    # 2. Загрузка письма в папку LETTERS/YYYY-MM-DD
    target_txt_dir = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["LETTERS"], date_folder_name)
    txt_res = upload_file_to_drive(drive_service, txt_path, target_txt_dir, "text/plain")
    links["txt"] = txt_res["link"]

    # 3. Загрузка JSON в папку JSON/YYYY-MM-DD
    target_json_dir = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["JSON"], date_folder_name)
    json_res = upload_file_to_drive(drive_service, json_path, target_json_dir, "application/json")
    links["json"] = json_res["link"]

    # 4. Запись строки в Google Sheets
    if spreadsheet_id and spreadsheet_id.strip():
        now_time = datetime.datetime.now().strftime("%H:%M:%S")
        row = [
            mapping["[[DATE]]"],
            now_time,
            audit_data.get("title", ""),
            audit_data.get("org_id", ""),
            audit_data.get("canonical_url", ""),
            mapping["[[NICHE]]"],
            audit_data.get("rating", ""),
            mapping["[[SCORE]]"],
            mapping["[[LOST_LEADS]]"],
            mapping["[[REV_LOSS_FMT]]"],
            links["pdf"],
            links["txt"],
            links["json"]
        ]
        append_row_to_google_sheet(sheets_service, spreadsheet_id.strip(), row)

    return links

# ==========================================================
# 3. АВТОПАРСЕР ЯНДЕКС КАРТ И DADATA
# ==========================================================

def clean_company_name(raw_title: str) -> str:
    t = raw_title.replace("— Яндекс Карты", "").replace("- Яндекс Карты", "")
    t = re.sub(r'^(?:Стоматология|Клиника|Медицинский центр|Автосервис)\s+', '', t, flags=re.IGNORECASE)
    t = re.split(r'[,|•·—–]', t)[0].strip()
    return t if t else raw_title.strip()


def fetch_yandex_maps_data(raw_url: str) -> Dict[str, Any]:
    url = raw_url.strip()
    if not url:
        raise ValueError("URL пуст.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }

    session = requests.Session()
    session.headers.update(headers)

    canonical_url = url
    try:
        resp = session.get(url, allow_redirects=True, timeout=6)
        canonical_url = resp.url
        html = resp.text
    except Exception:
        html = ""

    # Извлечение ID
    org_id = None
    m_id = re.search(r'/org/(?:[^/?#]+/)?(\d+)', canonical_url)
    if m_id:
        org_id = m_id.group(1)
    else:
        m_oid = re.search(r'[?&]oid=(\d+)', canonical_url)
        if m_oid:
            org_id = m_oid.group(1)

    # Извлечение названия
    title = None
    if html:
        m_og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_og:
            title = clean_company_name(m_og.group(1))
        if not title:
            m_t = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            if m_t:
                title = clean_company_name(m_t.group(1))

    if not title:
        m_slug = re.search(r'/org/([^/?#]+)/\d+', canonical_url)
        if m_slug:
            slug = m_slug.group(1)
            title = urllib.parse.unquote(slug).replace('_', ' ').replace('-', ' ').title()

    if not title or title.lower() in ["яндекс карты", "yandex maps"]:
        title = "Новая организация"

    if not org_id:
        org_id = "0000000000"

    # Рейтинг
    rating = 4.7
    if html:
        m_rate = re.search(r'itemprop=["\']ratingValue["\']\s+content=["\']([0-9.]+)["\']', html)
        if not m_rate:
            m_rate = re.search(r'class="business-rating-badge-view__rating">([0-9.]+)</span>', html)
        if m_rate:
            try:
                rating = float(m_rate.group(1))
            except ValueError:
                pass

    # Ниша
    low = (title + " " + canonical_url).lower()
    if any(k in low for k in ["стом", "dent", "зуб", "ортод"]):
        niche = "DENTISTRY"
    elif any(k in low for k in ["космет", "beauty", "эстет"]):
        niche = "COSMETOLOGY"
    elif any(k in low for k in ["авто", "сервис", "мотор", "ремонт"]):
        niche = "AUTOSERVICES"
    else:
        niche = "DENTISTRY"

    return {
        "title": title,
        "org_id": org_id,
        "rating": rating,
        "canonical_url": canonical_url,
        "niche": niche,
        "score": 66.5,
        "competitors": ["соседние клиники локации", "прямые конкуренты"],
    }


def fetch_dadata_parties(query: str, token: str) -> List[Dict[str, Any]]:
    if not query.strip() or not token.strip():
        return []
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
    headers = {
        "Authorization": f"Token {token.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"query": query.strip(), "count": 5}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=4)
        if r.status_code == 200:
            return r.json().get("suggestions", [])
    except Exception:
        pass
    return []

# ==========================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
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
    return clean if clean else "clinic"

# ==========================================================
# 5. ГЕНЕРАТОР ПЕРВОГО СООБЩЕНИЯ (ICEBREAKER)
# ==========================================================

def generate_icebreaker(
    title: str,
    rating: float | str,
    competitors: List[str],
    lost_leads: int,
    niche_genitive: str = "стоматологий",
) -> str:
    if competitors and len(competitors) >= 2:
        comp_str = f"«{competitors[0].strip('«»')}» и «{competitors[1].strip('«»')}»"
    elif competitors and len(competitors) == 1:
        comp_str = f"«{competitors[0].strip('«»')}»"
    else:
        comp_str = "прямые конкуренты района"

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
# 6. РАСЧЕТ ЮНИТ-ЭКОНОМИКИ
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

    failures = audit_data.get("top_failures", [
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
            "desc": "В карточке заполнено менее трети ключевых позиций. Поисковые алгоритмы Яндекса пессимизируют профиль по предметным запросам процедур."
        }
    ])

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
        "[[EXECUTIVE_SUMMARY]]": (
            f"Профиль «{title}» обладает высокой клинической репутацией ({rating}), однако из-за отсутствия "
            f"прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм "
            f"перенаправляет до {lost_leads} готовых обращений в месяц прямым конкурентам локации."
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
# 7. КОМПИЛЯТОР TYPST
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
        return False, f"Ошибка Typst: {e.stderr}"
    except FileNotFoundError:
        return False, "Утилита 'typst' CLI не установлена в PATH."
    finally:
        if temp_typ_path.exists():
            try:
                temp_typ_path.unlink()
            except OSError:
                pass

# ==========================================================
# 8. ИНТЕРФЕЙС STREAMLIT
# ==========================================================

def run_streamlit_app() -> None:
    st.set_page_config(
        page_title="PIN100 Analytics",
        page_icon="📍",
        layout="wide"
    )

    if "current_audit" not in st.session_state:
        st.session_state.current_audit = None
    if "drive_links" not in st.session_state:
        st.session_state.drive_links = None

    st.title("📍 PIN100 Analytics: Экспресс-аудит гео-карточки")
    st.caption("Вставьте ссылку на организацию в Яндекс Картах для автоматического расчета и выгрузки в Google Диск.")

    # Верхняя строка ввода ссылки
    with st.container():
        col_url, col_btn = st.columns([4, 1.2])
        with col_url:
            target_url = st.text_input(
                "Ссылка на организацию в Яндекс Картах:",
                placeholder="Вставьте ссылку: https://yandex.ru/maps/org/... или короткую https://yandex.ru/maps/-/... ",
                label_visibility="collapsed"
            )
        with col_btn:
            start_scan = st.button("🚀 Запустить аудит", type="primary", use_container_width=True)

    # Дополнительный поиск через DaData
    with st.expander("🔍 Или найти организацию по названию / ИНН через DaData", expanded=False):
        d_col1, d_col2 = st.columns([1, 2])
        with d_col1:
            dadata_token = st.text_input("API-ключ DaData", value=os.getenv("DADATA_API_KEY", ""), type="password")
        with d_col2:
            query_party = st.text_input("Название клиники или ИНН", placeholder="Например: Дентал Арт")

        if query_party.strip() and dadata_token.strip():
            results = fetch_dadata_parties(query_party, dadata_token)
            if results:
                s_map = {}
                for r in results:
                    c_name = r.get("data", {}).get("name", {}).get("short_with_opf") or r.get("value", "")
                    addr = r.get("data", {}).get("address", {}).get("value", "")
                    s_map[f"{c_name} — {addr}"] = (c_name, addr)

                chosen_lbl = st.selectbox("Выберите найденную организацию:", options=list(s_map.keys()))
                if st.button("Импортировать выбранную", use_container_width=True):
                    c_n, c_a = s_map[chosen_lbl]
                    st.session_state.current_audit = {
                        "title": c_n,
                        "org_id": "0000000000",
                        "rating": 4.8,
                        "canonical_url": f"https://yandex.ru/maps/?text={urllib.parse.quote_plus(c_n + ' ' + c_a)}",
                        "niche": "DENTISTRY",
                        "score": 67.0,
                        "competitors": ["соседние клиники района", "прямые конкуренты"],
                    }
                    st.session_state.drive_links = None
                    st.rerun()

    # Обработка вставленной ссылки
    if start_scan and target_url.strip():
        with st.spinner("Анализируем профиль организации на Картах..."):
            try:
                extracted = fetch_yandex_maps_data(target_url)
                st.session_state.current_audit = extracted
                st.session_state.drive_links = None
                st.success(f"Организация «{extracted['title']}» успешно определена!")
            except Exception as e:
                st.error(f"Не удалось разобрать ссылку: {e}")

    # Если аудит еще не начат
    if not st.session_state.current_audit:
        st.info("👆 Вставьте ссылку на любую организацию в поле выше и нажмите **«Запустить аудит»**.")
        return

    # РАБОЧАЯ ЗОНА С ДАННЫМИ
    audit = st.session_state.current_audit
    st.divider()

    # Боковая панель для точечной корректировки
    with st.sidebar:
        st.header("Настройки Google Таблицы")
        sheet_id = st.text_input(
            "ID Google Таблицы (для логов):",
            value=os.getenv("GOOGLE_SHEET_ID", ""),
            placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
            help="Часть URL таблицы между /d/ и /edit"
        )

        st.header("Параметры карточки")
        audit["title"] = st.text_input("Название организации", value=audit["title"])
        audit["org_id"] = st.text_input("ID в Яндекс Бизнесе", value=audit["org_id"])
        audit["rating"] = st.number_input("Рейтинг на Картах", min_value=1.0, max_value=5.0, value=float(audit["rating"]), step=0.1)
        audit["score"] = st.slider("Балл готовности профиля", min_value=20.0, max_value=98.0, value=float(audit["score"]), step=0.5)

        st.subheader("Конкуренты района")
        comp1 = st.text_input("Конкурент 1", value=audit["competitors"][0] if len(audit["competitors"]) > 0 else "")
        comp2 = st.text_input("Конкурент 2", value=audit["competitors"][1] if len(audit["competitors"]) > 1 else "")
        audit["competitors"] = [c for c in [comp1, comp2] if c.strip()]

        if st.button("🗑️ Сбросить и начать заново", use_container_width=True):
            st.session_state.current_audit = None
            st.session_state.drive_links = None
            st.rerun()

    # Юнит-экономика
    mapping = calculate_report_metrics(audit)

    col_l, col_r = st.columns([1.1, 0.9])

    with col_l:
        st.subheader(f"Карточка: «{audit['title']}»")
        if audit.get("canonical_url"):
            st.markdown(f"🔗 [Открыть организацию на Яндекс Картах]({audit['canonical_url']})")

        st.markdown("**Ключевые барьеры профиля (Стр. 3 отчета):**")
        st.markdown("1. **Отсутствие быстрой онлайн-записи (МИС)** — вечерний трафик уходит к конкурентам.")
        st.markdown("2. **Отсутствие витрины специалистов** — обезличенный профиль проигрывает карточкам с открытой командой.")
        st.markdown("3. **Фрагментарный прейскурант без цен «от...»** — пессимизация профиля по коммерческим запросам.")

        st.divider()

        # Блок сборки и сохранения на Google Диск
        st.subheader("Генерация и сохранение на Google Диск")
        template_file = Path("report_template.typ")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        date_tag = datetime.date.today().strftime("%Y-%m-%d")
        file_prefix = f"{sanitize_filename(audit['title'])}_{audit['org_id']}_{date_tag}"
        pdf_path = output_dir / f"{file_prefix}_report.pdf"
        txt_path = output_dir / f"{file_prefix}_icebreaker.txt"
        json_path = output_dir / f"{file_prefix}_data.json"

        btn_run = st.button("🚀 Скомпилировать PDF и сохранить на Google Диск", type="primary", use_container_width=True)

        if btn_run:
            if not template_file.exists():
                st.error("Файл 'report_template.typ' не найден рядом с app.py.")
            else:
                with st.spinner("Генерируем файлы и выгружаем в папки с датой на Google Диск..."):
                    # 1. Формирование текстов и JSON
                    n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
                    lost_leads_int = int(mapping["[[LOST_LEADS]]"])
                    icebreaker_text = generate_icebreaker(
                        title=audit["title"],
                        rating=audit["rating"],
                        competitors=audit["competitors"],
                        lost_leads=lost_leads_int,
                        niche_genitive=n_def["niche_genitive"]
                    )

                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(icebreaker_text)

                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(audit, f, ensure_ascii=False, indent=2)

                    # 2. Компиляция Typst
                    rendered = render_typst_template(template_file, mapping)
                    ok, err = compile_typst_pdf(rendered, pdf_path, output_dir)

                    if ok:
                        st.success("PDF отчет успешно скомпилирован локально.")
                        # 3. Выгрузка в Google Drive
                        try:
                            links = sync_results_to_google(
                                audit_data=audit,
                                mapping=mapping,
                                pdf_path=pdf_path,
                                txt_path=txt_path,
                                json_path=json_path,
                                spreadsheet_id=sheet_id
                            )
                            st.session_state.drive_links = links
                            st.balloons()
                        except Exception as ex:
                            st.error(f"Не удалось выгрузить на Google Диск: {ex}")
                    else:
                        st.warning(f"Ошибка Typst: {err}")

        # Отображение ссылок на Google Диск
        if st.session_state.drive_links:
            st.success("✅ Все материалы сохранены в целевые папки с текущей датой!")
            l = st.session_state.drive_links
            st.markdown(f"📄 **PDF на Google Диске:** [Открыть файл]({l.get('pdf', '#')})")
            st.markdown(f"✉️ **Письмо (TXT) на Google Диске:** [Открыть файл]({l.get('txt', '#')})")
            st.markdown(f"⚙️ **JSON на Google Диске:** [Открыть файл]({l.get('json', '#')})")

    with col_r:
        st.subheader("Расчетные показатели потерь")
        m1, m2 = st.columns(2)
        m1.metric("Оценка профиля", f"{mapping['[[SCORE]]']} / 100")
        m2.metric("Потери пациентов", f"~{mapping['[[LOST_LEADS]]']} чел/мес")

        m3, m4 = st.columns(2)
        m3.metric("Упущенная выручка", f"{mapping['[[REV_LOSS_FMT]]']} ₽/мес")
        m4.metric("Потери за неделю", f"~{mapping['[[WEEKLY_LOSS_FMT]]']} ₽/нед")

        st.divider()

        st.subheader("Первое сообщение для ЛПР (Icebreaker)")
        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
        icebreaker_txt = generate_icebreaker(
            title=audit["title"],
            rating=audit["rating"],
            competitors=audit["competitors"],
            lost_leads=lost_leads_int,
            niche_genitive=n_def["niche_genitive"]
        )

        st.text_area("Текст для отправки в мессенджер:", value=icebreaker_txt, height=210)


if __name__ == "__main__":
    run_streamlit_app()
