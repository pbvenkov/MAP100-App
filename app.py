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
# 1. ID ПАПОК GOOGLE DRIVE И ЭКОНОМИКА НИШ
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
    for path_str in ["credentials.json", "service_account.json"]:
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
    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{date_str}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    res = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": date_str,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_file_to_drive(drive_service: Any, local_path: Path, target_folder_id: str, mime_type: str) -> Dict[str, str]:
    metadata = {"name": local_path.name, "parents": [target_folder_id]}
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
    uploaded = drive_service.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    return {"id": uploaded.get("id", ""), "link": uploaded.get("webViewLink", "")}


def append_row_to_google_sheet(sheets_service: Any, spreadsheet_id: str, row_values: List[Any]) -> bool:
    try:
        body = {"values": [row_values]}
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Лист1!A:M",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        return True
    except Exception as e:
        st.warning(f"Запись в Google Таблицу пропущена: {e}")
        return False


def sync_results_to_google(
    audit_data: Dict[str, Any],
    mapping: Dict[str, str],
    pdf_path: Path,
    txt_path: Path,
    json_path: Path,
    spreadsheet_id: Optional[str] = None
) -> Dict[str, str]:
    creds = get_google_credentials()
    if not creds:
        raise FileNotFoundError("Ключ credentials.json не найден в каталоге проекта.")

    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)
    date_str = datetime.date.today().strftime("%Y-%m-%d")

    target_pdf = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["PDF"], date_str)
    pdf_res = upload_file_to_drive(drive_service, pdf_path, target_pdf, "application/pdf")

    target_txt = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["LETTERS"], date_str)
    txt_res = upload_file_to_drive(drive_service, txt_path, target_txt, "text/plain")

    target_json = get_or_create_date_folder(drive_service, GDRIVE_FOLDERS["JSON"], date_str)
    json_res = upload_file_to_drive(drive_service, json_path, target_json, "application/json")

    links = {"pdf": pdf_res["link"], "txt": txt_res["link"], "json": json_res["link"]}

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
# 3. ПАРСИНГ ГОТОВОГО JSON АУДИТА
# ==========================================================

def parse_incoming_audit_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализует сырой JSON карточки или внутреннего чеклиста."""
    title = data.get("title") or data.get("name") or "Новая организация"
    org_id = str(data.get("org_id") or data.get("id") or data.get("companyId") or "0000000000")
    rating = float(data.get("rating") or data.get("ratingValue") or data.get("reviewsRating") or 4.7)
    score = float(data.get("score") or data.get("totalScore") or 66.5)
    niche = data.get("niche") or "DENTISTRY"

    comps = data.get("competitors", [])
    if not comps or not isinstance(comps, list):
        comps = ["соседние клиники района", "прямые конкуренты"]

    n_def = NICHE_CONFIG.get(niche, NICHE_CONFIG["DENTISTRY"])
    benchmark_leads = int(data.get("benchmark_leads") or n_def["benchmark_leads"])
    base_check = int(data.get("base_check") or n_def["base_check"])
    ltv_months = int(data.get("ltv_months") or n_def["ltv_months"])

    fails = data.get("top_failures")
    if not fails or not isinstance(fails, list) or len(fails) < 3:
        fails = [
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
        ]

    return {
        "title": title,
        "org_id": org_id,
        "rating": rating,
        "score": score,
        "niche": niche,
        "canonical_url": data.get("canonical_url") or data.get("url") or "",
        "competitors": comps,
        "benchmark_leads": benchmark_leads,
        "base_check": base_check,
        "ltv_months": ltv_months,
        "top_failures": fails,
        "date": data.get("date") or datetime.date.today().strftime("%d.%m.%Y"),
        "date_raw": data.get("date_raw") or datetime.date.today().strftime("%Y-%m-%d"),
    }

# ==========================================================
# 4. РЕЗЕРВНЫЙ ПАРСЕР ЯНДЕКС КАРТ И DADATA
# ==========================================================

def fetch_yandex_maps_data(raw_url: str) -> Dict[str, Any]:
    url = raw_url.strip()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })

    try:
        resp = session.get(url, allow_redirects=True, timeout=5)
        canonical = resp.url
        html = resp.text
    except Exception:
        canonical = url
        html = ""

    org_id = "0000000000"
    m_id = re.search(r'/org/(?:[^/?#]+/)?(\d+)', canonical)
    if m_id:
        org_id = m_id.group(1)
    else:
        m_oid = re.search(r'[?&]oid=(\d+)', canonical)
        if m_oid:
            org_id = m_oid.group(1)

    title = "Новая организация"
    if html:
        m_og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if m_og:
            title = m_og.group(1).replace("— Яндекс Карты", "").split(",")[0].strip()

    rating = 4.7
    if html:
        m_rate = re.search(r'itemprop=["\']ratingValue["\']\s+content=["\']([0-9.]+)["\']', html)
        if m_rate:
            try:
                rating = float(m_rate.group(1))
            except ValueError:
                pass

    return parse_incoming_audit_json({
        "title": title,
        "org_id": org_id,
        "rating": rating,
        "score": 66.5,
        "url": canonical,
    })


def fetch_dadata_parties(query: str, token: str) -> List[Dict[str, Any]]:
    if not query.strip() or not token.strip():
        return []
    url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
    headers = {"Authorization": f"Token {token.strip()}", "Content-Type": "application/json"}
    try:
        r = requests.post(url, headers=headers, json={"query": query.strip(), "count": 5}, timeout=4)
        if r.status_code == 200:
            return r.json().get("suggestions", [])
    except Exception:
        pass
    return []

# ==========================================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
# ==========================================================

def format_currency(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", " ")

def get_declension(number: int, word_type: str = "пациент") -> str:
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type in ["пациент", "клиент"]:
        if 11 <= n <= 19:
            return f"{word_type}ов"
        if n1 == 1:
            return word_type
        if 2 <= n1 <= 4:
            return f"{word_type}а"
        return f"{word_type}ов"
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

    leads_range_str = f"{max(1, lost_leads - 2)}–{lost_leads + 3}"

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

    table_declension = get_declension(lost_leads, niche_info["client_word"])
    failures = audit_data.get("top_failures", [])

    return {
        "[[TITLE]]": title,
        "[[NICHE]]": niche_info["niche_name"],
        "[[DATE]]": audit_data.get("date", datetime.date.today().strftime("%d.%m.%Y")),
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

def render_typst_template(template_path: Path, mapping: Dict[str, str]) -> str:
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    for placeholder, val in mapping.items():
        content = content.replace(placeholder, str(val))
    return content

def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> Tuple[bool, str]:
    temp_typ = work_dir / f"temp_{output_pdf_path.stem}.typ"
    try:
        with open(temp_typ, "w", encoding="utf-8") as f:
            f.write(typst_content)
        cmd = ["typst", "compile", str(temp_typ), str(output_pdf_path)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, f"Ошибка Typst: {e.stderr}"
    except FileNotFoundError:
        return False, "Утилита Typst не найдена в PATH."
    finally:
        if temp_typ.exists():
            try:
                temp_typ.unlink()
            except OSError:
                pass

# ==========================================================
# 6. ИНТЕРФЕЙС STREAMLIT
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

    # Боковая панель: Системные настройки
    with st.sidebar:
        st.header("⚙️ Системные настройки")
        with st.expander("Ключи интеграций", expanded=False):
            dadata_token = st.text_input(
                "API-ключ DaData",
                value=st.session_state.get("dadata_key", os.getenv("DADATA_API_KEY", "")),
                type="password"
            )
            if dadata_token:
                st.session_state["dadata_key"] = dadata_token

            sheet_id = st.text_input(
                "ID Google Таблицы (для логов)",
                value=st.session_state.get("sheet_id", os.getenv("GOOGLE_SHEET_ID", "")),
                help="Часть URL таблицы между /d/ и /edit"
            )
            if sheet_id:
                st.session_state["sheet_id"] = sheet_id

        if st.session_state.current_audit:
            st.divider()
            st.subheader("Корректировка текущей карточки")
            cur = st.session_state.current_audit
            cur["title"] = st.text_input("Название", value=cur["title"])
            cur["rating"] = st.number_input("Рейтинг", min_value=1.0, max_value=5.0, value=float(cur["rating"]), step=0.1)
            cur["score"] = st.slider("Балл готовности", min_value=20.0, max_value=98.0, value=float(cur["score"]), step=0.5)

            if st.button("🗑️ Очистить и ввести другую", use_container_width=True):
                st.session_state.current_audit = None
                st.session_state.drive_links = None
                st.rerun()

    st.title("📍 PIN100 Analytics: Экспресс-аудит гео-карточки")

    # ГЛАВНЫЙ БЛОК ВВОДА: Ссылка на Карты первой по умолчанию
    tab_url, tab_json, tab_dadata = st.tabs([
        "🔗 Ссылка на Яндекс Карты",
        "📋 Вставить готовый JSON",
        "🏢 Поиск по названию / ИНН"
    ])

    # 1. Вкладка по умолчанию: Ссылка на Яндекс Карты
    with tab_url:
        col_u1, col_u2 = st.columns([4, 1.2])
        with col_u1:
            target_url = st.text_input(
                "Ссылка на профиль в Яндекс Картах:",
                placeholder="Вставьте ссылку: https://yandex.ru/maps/org/... или короткую https://yandex.ru/maps/-/... ",
                label_visibility="collapsed"
            )
        with col_u2:
            if st.button("🚀 Запустить аудит", type="primary", use_container_width=True):
                if target_url.strip():
                    with st.spinner("Извлекаем параметры карточки..."):
                        try:
                            st.session_state.current_audit = fetch_yandex_maps_data(target_url)
                            st.session_state.drive_links = None
                            st.success("Карточка успешно определена!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка разбора ссылки: {e}")

    # 2. Вкладка: Загрузка готового JSON
    with tab_json:
        col_j1, col_j2 = st.columns([1.5, 2.5])
        with col_j1:
            uploaded_file = st.file_uploader("Загрузить файл .json аудита:", type=["json"])
            if uploaded_file is not None:
                try:
                    raw_data = json.load(uploaded_file)
                    st.session_state.current_audit = parse_incoming_audit_json(raw_data)
                    st.session_state.drive_links = None
                    st.success(f"JSON загружен! Организация: «{st.session_state.current_audit['title']}»")
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка чтения JSON файла: {e}")

        with col_j2:
            json_text = st.text_area(
                "Или вставьте JSON код из буфера обмена:",
                height=130,
                placeholder='{\n  "title": "Клиника",\n  "rating": 4.8,\n  "score": 67.5,\n  "competitors": ["РозДент"]\n}'
            )
            if st.button("⚡ Применить JSON и рассчитать", use_container_width=True):
                if json_text.strip():
                    try:
                        raw_data = json.loads(json_text)
                        st.session_state.current_audit = parse_incoming_audit_json(raw_data)
                        st.session_state.drive_links = None
                        st.success("Данные успешно применены!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Невалидный JSON: {e}")

    # 3. Вкладка: Поиск по названию / ИНН
    with tab_dadata:
        query_company = st.text_input("Введите название компании или ИНН:", placeholder="Например: Дентал Арт")
        active_token = st.session_state.get("dadata_key", os.getenv("DADATA_API_KEY", ""))

        if query_company.strip():
            if not active_token:
                st.info("Укажите API-ключ DaData в боковом меню (⚙️ Системные настройки) для активации поиска.")
            else:
                found = fetch_dadata_parties(query_company, active_token)
                if found:
                    opt_map = {}
                    for item in found:
                        nm = item.get("data", {}).get("name", {}).get("short_with_opf") or item.get("value", "")
                        ad = item.get("data", {}).get("address", {}).get("value", "")
                        opt_map[f"{nm} — {ad}"] = (nm, ad)

                    choice = st.selectbox("Выберите организацию из списка:", options=list(opt_map.keys()))
                    if st.button("Использовать эту организацию", use_container_width=True):
                        c_name, c_addr = opt_map[choice]
                        search_url = f"https://yandex.ru/maps/?text={urllib.parse.quote_plus(c_name + ' ' + c_addr)}"
                        st.session_state.current_audit = parse_incoming_audit_json({
                            "title": c_name,
                            "url": search_url,
                            "rating": 4.8,
                            "score": 67.0
                        })
                        st.session_state.drive_links = None
                        st.rerun()
                else:
                    st.caption("Организаций не найдено.")

    # Если аудит еще не запущен
    if not st.session_state.current_audit:
        st.divider()
        st.info("👆 Укажите ссылку на Яндекс Карты или загрузите готовый JSON компании для начала расчета.")
        return

    # РАБОЧИЙ ДАШБОРД АУДИТА
    audit = st.session_state.current_audit
    mapping = calculate_report_metrics(audit)
    st.divider()

    col_l, col_r = st.columns([1.1, 0.9])

    with col_l:
        st.subheader(f"Карточка: «{audit['title']}»")
        if audit.get("canonical_url"):
            st.markdown(f"🔗 [Открыть в Яндекс Картах]({audit['canonical_url']})")

        st.markdown("**Ключевые барьеры карточки (Стр. 3 отчета):**")
        for idx, f in enumerate(audit.get("top_failures", []), 1):
            st.markdown(f"**{idx}. {f['title']}**")
            st.caption(f["desc"])

        st.divider()

        # Генерация и синхронизация
        st.subheader("Генерация и сохранение на Google Диск")
        template_file = Path("report_template.typ")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        date_tag = datetime.date.today().strftime("%Y-%m-%d")
        file_prefix = f"{sanitize_filename(audit['title'])}_{audit['org_id']}_{date_tag}"
        pdf_path = output_dir / f"{file_prefix}_report.pdf"
        txt_path = output_dir / f"{file_prefix}_icebreaker.txt"
        json_path = output_dir / f"{file_prefix}_data.json"

        if st.button("🚀 Скомпилировать PDF и отправить на Google Диск", type="primary", use_container_width=True):
            if not template_file.exists():
                st.error("Шаблон report_template.typ не найден рядом с app.py.")
            else:
                with st.spinner("Компилируем PDF и сохраняем на Google Диск..."):
                    lost_leads_int = int(mapping["[[LOST_LEADS]]"])
                    n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
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

                    rendered = render_typst_template(template_file, mapping)
                    ok, err = compile_typst_pdf(rendered, pdf_path, output_dir)

                    if ok:
                        st.success("PDF отчет успешно собран локально.")
                        target_sheet = st.session_state.get("sheet_id", os.getenv("GOOGLE_SHEET_ID", ""))
                        try:
                            links = sync_results_to_google(
                                audit_data=audit,
                                mapping=mapping,
                                pdf_path=pdf_path,
                                txt_path=txt_path,
                                json_path=json_path,
                                spreadsheet_id=target_sheet
                            )
                            st.session_state.drive_links = links
                            st.balloons()
                        except Exception as ex:
                            st.error(f"Не удалось выгрузить на Google Диск: {ex}")
                    else:
                        st.error(f"Ошибка компиляции Typst: {err}")

        if st.session_state.drive_links:
            st.success("✅ Все материалы сохранены в целевые папки с текущей датой!")
            l = st.session_state.drive_links
            st.markdown(f"📄 **PDF на Диске:** [Открыть отчет]({l.get('pdf', '#')})")
            st.markdown(f"✉️ **Письмо на Диске:** [Открыть текст]({l.get('txt', '#')})")
            st.markdown(f"⚙️ **JSON на Диске:** [Открыть файл]({l.get('json', '#')})")

    with col_r:
        st.subheader("Расчетные показатели потерь")
        m1, m2 = st.columns(2)
        m1.metric("Оценка профиля", f"{mapping['[[SCORE]]']} / 100")
        m2.metric("Потери пациентов", f"~{mapping['[[LOST_LEADS]]']} чел/мес")

        m3, m4 = st.columns(2)
        m3.metric("Упущенная выручка", f"{mapping['[[REV_LOSS_FMT]]']} ₽/мес")
        m4.metric("Потери за неделю", f"~{mapping['[[WEEKLY_LOSS_FMT]]']} ₽/нед")

        st.divider()

        st.subheader("Первое сообщение руководителю (Icebreaker)")
        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        n_def = NICHE_CONFIG.get(audit.get("niche", "DENTISTRY"), NICHE_CONFIG["DENTISTRY"])
        icebreaker_txt = generate_icebreaker(
            title=audit["title"],
            rating=audit["rating"],
            competitors=audit["competitors"],
            lost_leads=lost_leads_int,
            niche_genitive=n_def["niche_genitive"]
        )
        st.text_area("Текст для WhatsApp / Telegram / Email:", value=icebreaker_txt, height=210)


if __name__ == "__main__":
    run_streamlit_app()
