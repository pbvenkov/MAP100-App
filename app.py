import streamlit as st
import requests
import time
import json
import numpy as np
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# ==========================================
# 2. ПАРСЕР GOOGLE ТАБЛИЦЫ И APIFY
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(credentials).open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        st.stop()

def get_rules_from_sheets():
    doc = init_google_sheets()
    # UNFORMATTED_VALUE отключает форматирование Google (защита от запятых)
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    
    for r in records:
        raw_val = r.get('Балл', 0.0)
        try:
            if isinstance(raw_val, (int, float)):
                r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError:
            r['Балл'] = 0.0
            
        # Защита от пустых статусов
        r['Статус'] = str(r.get('Статус', 'Заглушка')).strip()
            
    return records

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: raise Exception(run_req['error'])

    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception("⏱ Таймаут парсера.")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1

    if status != "SUCCEEDED": raise Exception("Ошибка парсинга Apify.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: raise Exception("Нет данных.")
    return dataset[0]

# ==========================================
# 3. МОДУЛЬНАЯ АРХИТЕКТУРА (УРОВНИ 1 и 2)
# ==========================================

def calculate_prof_rules(data):
    scores = {}
    logs = []
    
    # --- БАЗА И СИНЯЯ ГАЛОЧКА (12.1, 01.1, 03.1, 05.1, 07.1) ---
    has_blue_tick = data.get('isVerifiedOwner', False)
    if has_blue_tick:
        scores['PROF-12.1'] = 4.0
        logs.append("✅ [PROF-12.1] Синяя галочка: Базовые поля засчитаны автоматически.")
        scores['PROF-01.1'] = 0.5
        scores['PROF-03.1'] = 0.5
        scores['PROF-05.1'] = 1.0
        scores['PROF-07.1'] = 1.0
    else:
        if len(data.get('title', '')) > 2: scores['PROF-01.1'] = 0.5
        if len(data.get('categories') or []) > 0: scores['PROF-03.1'] = 0.5
        if data.get('phones'): scores['PROF-05.1'] = 1.0
        if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = 1.0

    # --- ДОП. ПРОВЕРКИ ПРОФИЛЯ ---
    if data.get('phones'): # PROF-05.2 (Формат)
        if any("доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10 for p in data.get('phones')):
            scores['PROF-05.2'] = 0.5
            
    if data.get('features') and len(data['features']) > 0: scores['PROF-08.1'] = 0.5 # Атрибуты
    
    desc = data.get('description') or ''
    if len(desc) > 1500: scores['PROF-10.1'] = 0.5 # Объем описания
    
    website = data.get('url') or data.get('website') or ''
    if website: 
        scores['PROF-04.1'] = 0.5 # Рабочая ссылка
        if "utm_" in str(website).lower():
            scores['PROF-04.2'] = 0.5 # UTM-метки

    # --- КАТАЛОГ (11.X) ---
    products = (data.get('menu') or {}).get('items') or data.get('productCatalog') or []
    if len(products) >= 10:
        scores['PROF-11.1'] = 1.5
        with_photo = sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image'))
        with_price = sum(1 for p in products if p.get('price'))
        with_desc = sum(1 for p in products if len(str(p.get('description') or '')) > 50)
        categories_set = set(p['category'].get('name') if isinstance(p.get('category'), dict) else p.get('category') for p in products if p.get('category'))
        
        if (with_photo / len(products)) >= 0.8: scores['PROF-11.2'] = 1.0
        if (with_price / len(products)) >= 0.8: scores['PROF-11.3'] = 1.0
        if (with_desc / len(products)) >= 0.8: scores['PROF-11.4'] = 1.0
        if len(categories_set) >= 2: scores['PROF-11.5'] = 0.5
            
    # --- ССЫЛКИ (13.X) ---
    links_str = " ".join(str(l).lower() for l in (data.get('links') or []) + (data.get('socials') or []))
    if any(s in links_str for s in ["t.me", "tg://", "wa.me", "whatsapp"]): scores['PROF-13.1'] = 0.5
    if any(s in links_str for s in ["vk.com", "youtube", "dzen"]): scores['PROF-13.2'] = 0.5

    return scores, logs

def calculate_cont_rules(data):
    scores, logs = {}, []
    photo_count = data.get('photoCount') or data.get('photosCount') or 0
    if photo_count >= 15: 
        scores['CONT-36.1'] = 1.5
        logs.append(f"📸 [CONT-36.1] Найдено {photo_count} фото (>= 15).")
    if photo_count >= 30: 
        scores['CONT-36.2'] = 1.0
        logs.append(f"📸 [CONT-36.2] Найдено {photo_count} фото (>= 30).")
    return scores, logs

def calculate_rep_rules(data):
    scores, logs = {}, []
    rating = data.get('rating') or 0.0
    if rating >= 4.5: scores['REP-27.1'] = 2.0
    if rating >= 4.8: scores['REP-27.2'] = 2.0
    
    rev_count = data.get('reviewsCount') or data.get('ratingsCount') or 0
    if rev_count >= 50: scores['REP-28.1'] = 2.0
    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    links_str = " ".join(str(l).lower() for l in (data.get('links') or []) + (data.get('socials') or []))
    features_str = " ".join(str(f).lower() for f in (data.get('features') or []))
    
    # Поиск систем онлайн-записи
    booking_systems = ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн', 'nethouse']
    if any(b in links_str or b in features_str for b in booking_systems):
        scores['CONV-48.1'] = 3.0
        
    # Чат с компанией
    if "chat" in features_str or data.get('isChatEnabled') == True:
        scores['CONV-50.1'] = 1.0
        
    return scores, logs

def calculate_seo_rules(data):
    scores, logs = {}, []
    address = data.get('address') or ''
    if len(address) > 5:  # Базовая проверка, что адрес не пустой
        scores['SEO-18.1'] = 0.5
    return scores, logs

def calculate_all_python_rules(data):
    all_scores, all_logs = {}, []
    
    # Запускаем все модули
    mods = [
        calculate_prof_rules(data),
        calculate_cont_rules(data),
        calculate_rep_rules(data),
        calculate_conv_rules(data),
        calculate_seo_rules(data)
    ]
    
    for s_dict, l_list in mods:
        all_scores.update(s_dict)
        all_logs.extend(l_list)
        
    return all_scores, all_logs


# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Полуавтомат", page_icon="📍", layout="wide")

try:
    rules_data = get_rules_from_sheets()
except Exception as e:
    st.error("⚠️ Не удалось загрузить базу правил.")
    st.stop()

# --- САЙДБАР: ПУЛЬТ РУЧНОГО УПРАВЛЕНИЯ (УРОВЕНЬ 3) ---
manual_rules = [r for r in rules_data if r.get('Статус') == "Ручной"]

manual_overrides = {}
with st.sidebar:
    st.header("🎛 Ручная оценка")
    st.caption("Оцените смысловые критерии самостоятельно.")
    
    current_prefix = ""
    for r in manual_rules:
        code = str(r.get('Код', '')).strip()
        if not code: continue
            
        prefix = code.split('-')[0] if '-' in code else "ДРУГОЕ"
        if prefix != current_prefix:
            st.markdown(f"### Блок {prefix}")
            current_prefix = prefix
            
        name = str(r.get('Критерий', '')).strip()
        max_score = float(r.get('Балл', 1.0))
        
        if max_score > 0:
            val = st.number_input(f"[{code}] {name}", min_value=0.0, max_value=max_score, value=0.0, step=0.5, help=str(r.get('Инструкция для ИИ', '')))
            manual_overrides[code] = val

# --- ОСНОВНОЙ ЭКРАН ---
st.title("📍 MAP100: AI-Аудитор (Версия 5.3 - Расширенная)")

# Панель статистики
stat_python = sum(1 for r in rules_data if r.get('Статус') == "Python")
stat_manual = sum(1 for r in rules_data if r.get('Статус') == "Ручной")
stat_stub = sum(1 for r in rules_data if r.get('Статус') not in ["Python", "Ручной"] and str(r.get('Код', '')).strip())

col_s1, col_s2, col_s3 = st.columns(3)
col_s1.metric("🟢 Готово (Python)", stat_python)
col_s2.metric("🧠 Ручной режим", stat_manual)
col_s3.metric("🟡 В разработке (Заглушки)", stat_stub)
st.divider()

yandex_url = st.text_input("Ссылка на карточку Яндекс.Бизнеса")

if st.button("🚀 Запустить аудит", type="primary", use_container_width=True):
    if not yandex_url or "yandex" not in yandex_url.lower():
        st.error("❌ Введите корректную ссылку на Яндекс.Карты.")
    else:
        doc = init_google_sheets()
        
        with st.spinner("Python собирает данные и применяет правила..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                company_name = raw_yandex_data.get('title', 'Без названия')
                python_scores_dict, python_logs = calculate_all_python_rules(raw_yandex_data)
            except Exception as e:
                st.error(f"Ошибка сбора данных: {e}")
                st.stop()
                
            # СЛИЯНИЕ ВСЕХ ДАННЫХ
            final_scores_dict = {}
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                
                max_score = float(r.get('Балл', 0.0))
                status = r.get('Статус', 'Заглушка')
                current_val = 0.0
                
                # Если статус Python -> берем из расчетов
                if status == "Python" and code in python_scores_dict:
                    current_val = min(float(python_scores_dict[code]), max_score)
                
                # Если статус Ручной -> берем из сайдбара
                elif status == "Ручной" and code in manual_overrides:
                    current_val = min(float(manual_overrides[code]), max_score)
                
                # Если статус Заглушка -> остается 0.0
                
                final_scores_dict[code] = current_val
                
            final_total_score = sum(final_scores_dict.values())
            
            # --- ВЫВОД НА ЭКРАН ---
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"🏢 {company_name}")
            with col2:
                if final_total_score >= 80: color = "normal"
                elif final_total_score >= 50: color = "off"
                else: color = "inverse"
                st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100", delta_color=color)

            with st.expander("📊 Детализация баллов по критериям"):
                st.json(final_scores_dict)

            # --- ЗАПИСЬ В ТАБЛИЦУ ---
            try:
                results_sheet = doc.worksheet("Results")
                headers = results_sheet.row_values(1)
                if not headers: headers = ["Дата", "Ссылка", "Компания", "Общий балл"]
                
                headers_changed = False
                for code in final_scores_dict.keys():
                    if code not in headers:
                        headers.append(code)
                        headers_changed = True
                
                if headers_changed:
                    cell_list = results_sheet.range(1, 1, 1, len(headers))
                    for i, val in enumerate(headers): cell_list[i].value = val
                    results_sheet.update_cells(cell_list)

                row_data = []
                for h in headers:
                    if h == "Дата": row_data.append(time.strftime("%d.%m.%Y %H:%M:%S"))
                    elif h == "Ссылка": row_data.append(yandex_url)
                    elif h == "Компания": row_data.append(company_name)
                    elif h == "Общий балл": row_data.append(final_total_score)
                    else: row_data.append(final_scores_dict.get(h, 0.0))

                results_sheet.append_row(row_data)
                st.success("✅ Результат успешно сохранен в базу!")
            except:
                st.warning("Не удалось сохранить в результаты (проверьте вкладку Results).")

# ==========================================
# 5. СЕРВИСНАЯ ПАНЕЛЬ ДЛЯ ЗАПОЛНЕНИЯ ТАБЛИЦЫ
# ==========================================
st.divider()
st.subheader("🛠 Сервисная панель разработчика")
if st.button("🪄 Магия: Авто-разметка столбца 'Статус' в Google Таблице"):
    with st.spinner("Подключаюсь к базе и расставляю статусы..."):
        try:
            doc = init_google_sheets()
            sheet = doc.worksheet("Rules")
            headers = sheet.row_values(1)
            
            if "Статус" not in headers:
                col_idx = len(headers) + 1
                sheet.update_cell(1, col_idx, "Статус")
            else:
                col_idx = headers.index("Статус") + 1
                
            records = sheet.get_all_records()
            
            # РАСШИРЕННЫЙ СПИСОК (25 метрик)
            python_codes = [
                "PROF-01.1", "PROF-03.1", "PROF-05.1", "PROF-05.2", 
                "PROF-07.1", "PROF-08.1", "PROF-11.1", "PROF-11.2", 
                "PROF-11.3", "PROF-11.4", "PROF-11.5", "PROF-12.1", 
                "PROF-13.1", "PROF-13.2", "CONT-36.1", "CONT-36.2",
                "REP-27.1", "REP-27.2", "REP-28.1", "CONV-48.1",
                "CONV-50.1", "PROF-04.1", "PROF-04.2", "PROF-10.1",
                "SEO-18.1"
            ]
            
            cell_list = sheet.range(2, col_idx, len(records) + 1, col_idx)
            
            for i, row in enumerate(records):
                code = str(row.get('Код', '')).strip()
                how = str(row.get('Как считаем', '')).strip().lower()
                
                if code in python_codes:
                    cell_list[i].value = "Python"
                elif "ии" in how or "ручн" in how or "эксперт" in str(row.get('Режим Эксперта', '')).lower():
                    cell_list[i].value = "Ручной"
                else:
                    cell_list[i].value = "Заглушка"
                    
            sheet.update_cells(cell_list)
            st.success("✅ Готово! Откройте вашу Google Таблицу — столбец 'Статус' идеально заполнен. Перезагрузите страницу!")
            st.balloons()
            
        except Exception as e:
            st.error(f"Произошла ошибка при обновлении таблицы: {e}")
