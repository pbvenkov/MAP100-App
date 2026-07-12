import streamlit as st
import requests
import time
import json
import numpy as np
import re
from datetime import datetime
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И КЛЮЧЕЙ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. ФУНКЦИИ И СТРОГИЙ ПАРСЕР ТАБЛИЦЫ
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets", 
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        return gc.open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        st.stop()

def get_rules_from_sheets():
    doc = init_google_sheets()
    
    # ВОЛШЕБНАЯ СТРОЧКА! UNFORMATTED_VALUE отключает форматирование Google
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    
    for r in records:
        raw_val = r.get('Балл', 0.0)
        r['DEBUG_RAW_SCORE'] = raw_val # Сохраняем истинное лицо Google для дебага
        try:
            if isinstance(raw_val, (int, float)):
                r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError:
            r['Балл'] = 0.0
            
    return records

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_payload = {"startUrls": [{"url": yandex_url}], "maxItems": 1}
    run_req = requests.post(run_url, json=run_payload)
    run_data = run_req.json()

    if 'error' in run_data:
        raise Exception(run_data['error'])

    run_id = run_data['data']['id']
    default_dataset_id = run_data['data']['defaultDatasetId']

    status = "RUNNING"
    retries = 0
    max_retries = 30
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= max_retries:
            raise Exception("⏱ Превышено время ожидания от парсера (таймаут). Попробуйте позже.")
        time.sleep(5)
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}"
        status = requests.get(status_url).json()['data']['status']
        retries += 1

    if status != "SUCCEEDED":
        raise Exception("Ошибка при парсинге данных Apify.")

    dataset_url = f"https://api.apify.com/v2/datasets/{default_dataset_id}/items?token={APIFY_API_TOKEN}"
    dataset_req = requests.get(dataset_url).json()
    
    if not dataset_req:
        raise Exception("Парсер не нашел данных.")
        
    return dataset_req[0]

# ==========================================
# 3. АНАЛИЗАТОР PYTHON
# ==========================================
def calculate_python_scores(data):
    scores = {}
    details = []

    title = data.get('title') or ''
    description = data.get('description') or ''
    categories = data.get('categories') or []
    phones = data.get('phones') or []
    links = (data.get('links') or []) + (data.get('socials') or [])
    features = data.get('features') or []
    
    if len(title) > 2:
        scores['PROF-01.1'] = 0.5

    if len(categories) > 1:
        scores['PROF-03.1'] = 0.5
        details.append(f"✅ [PROF-03.1] Доп. категории: {len(categories)-1} шт.")

    if len(phones) > 0:
        scores['PROF-05.1'] = 1.0
        
    valid_phone = False
    for p in phones:
        p_str = str(p).lower()
        if "доб" not in p_str and len(re.sub(r'\D', '', p_str)) >= 10:
            valid_phone = True
            break
    if valid_phone:
        scores['PROF-05.2'] = 0.5

    if len(data.get('schedule') or data.get('workingHours') or []) >= 7:
        scores['PROF-07.1'] = 1.0

    if len(features) > 0:
        scores['PROF-08.1'] = 0.5

    desc_len = len(description)
    if desc_len >= 1500:
        scores['PROF-10.1'] = 0.5
        details.append(f"✅ [PROF-10.1] Описание длинное: {desc_len} симв.")
    else:
        details.append(f"❌ [PROF-10.1] Описание короткое: {desc_len}/1500 симв.")

    if data.get('isVerifiedOwner') == True:
        scores['PROF-12.1'] = 4.0
        details.append("✅ [PROF-12.1] Аккаунт верифицирован (+4.0)")
    else:
        details.append("❌ [PROF-12.1] Отсутствует Синяя галочка (0.0)")

    photo_count = data.get('photoCount') or data.get('photosCount') or 0
    if photo_count >= 15:
        scores['CONT-36.1'] = 1.5
        if photo_count >= 30:
            scores['CONT-36.2'] = 1.0
        details.append(f"✅ [CONT-36] Галерея: {photo_count} фото.")

    menu_dict = data.get('menu') or {}
    products = menu_dict.get('items') or []
    if not products:
        products = data.get('productCatalog') or []
        
    if len(products) >= 10:
        scores['PROF-11.1'] = 1.5
        details.append(f"✅ [PROF-11.1] Каталог заполнен: {len(products)} позиций.")
        
        with_photo = sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image'))
        with_price = sum(1 for p in products if p.get('price'))
        with_desc = sum(1 for p in products if len(str(p.get('description') or '')) > 100)
        
        categories_set = set(p.get('category', {}).get('name') or p.get('category') for p in products if p.get('category'))
        
        if (with_photo / len(products)) >= 0.8:
            scores['PROF-11.2'] = 1.0
        if (with_price / len(products)) >= 0.8:
            scores['PROF-11.3'] = 1.0
        if (with_desc / len(products)) >= 0.8:
            scores['PROF-11.4'] = 1.0
        if len(categories_set) >= 2:
            scores['PROF-11.5'] = 0.5
    else:
        details.append(f"❌ [PROF-11.1] Мало товаров в каталоге: {len(products)} из 10.")

    links_str = " ".join(str(l).lower() for l in links)
    features_str = " ".join(str(f).lower() for f in features)
    
    if "vk.com" in links_str or "youtube" in links_str or "dzen" in links_str:
        scores['PROF-13.2'] = 0.5
    if "t.me" in links_str or "tg://" in links_str or "wa.me" in links_str or "whatsapp" in links_str:
        scores['PROF-13.1'] = 0.5
        
    booking_markers = ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн']
    if any(b in links_str or b in features_str for b in booking_markers):
        scores['CONV-48.1'] = 3.0 
        details.append("✅ [CONV-48.1] Найдена кнопка онлайн-записи (+3.0)")

    if "chat" in features_str or data.get('isChatEnabled') == True:
         scores['CONV-50.1'] = 1.0
         
    rating = data.get('rating') or 0
    if rating >= 4.8:
        scores['REP-27.2'] = 2.0
        scores['REP-27.1'] = 2.0
    elif rating >= 4.5:
        scores['REP-27.1'] = 2.0

    reviews_count = data.get('ratingsCount') or data.get('reviewsCount') or 0
    if reviews_count >= 50:
        scores['REP-28.1'] = 2.0

    reviews_data = data.get('reviews') or []
    response_times = []
    
    if reviews_data:
        last_rev_date_str = reviews_data[0].get("date")
        if last_rev_date_str:
            try:
                r_date = datetime.strptime(last_rev_date_str[:19], "%Y-%m-%dT%H:%M:%S")
                if (datetime.now() - r_date).days <= 14:
                    scores['REP-29.1'] = 2.0
            except Exception: pass

    for rev in reviews_data:
        if rev.get("businessComment") and rev.get("date") and rev.get("businessCommentDate"):
            try:
                r_date = datetime.strptime(rev["date"][:19], "%Y-%m-%dT%H:%M:%S")
                c_date = datetime.strptime(rev["businessCommentDate"][:19], "%Y-%m-%dT%H:%M:%S")
                response_times.append((c_date - r_date).days)
            except Exception:
                pass
                
    if response_times:
        median_speed = np.median(response_times)
        if median_speed <= 3:
            scores['REP-30.2'] = 2.0
            details.append(f"✅ [REP-30.2] Медиана ответов: {median_speed} дн. (+2.0)")

    return sum(scores.values()), details, scores

def trim_for_ai(raw_data):
    trimmed = {
        "title": raw_data.get("title") or "",
        "description": raw_data.get("description") or "",
        "categories": raw_data.get("categories") or [],
        "features": list((raw_data.get("features") or {}).keys()),
        "products": [],
        "reviews": []
    }
    
    menu_dict = raw_data.get('menu') or {}
    products = menu_dict.get('items') or []
    if products:
        trimmed["products"] = [p.get("title", "") for p in products[:15]]
    
    for r in (raw_data.get("reviews") or [])[:10]:
        trimmed["reviews"].append({
            "text": r.get("text", ""),
            "rating": r.get("rating", ""),
            "owner_reply": r.get("businessComment", "")
        })
    return trimmed

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА С ДЕБАГГЕРОМ
# ==========================================
st.set_page_config(page_title="MAP100 | Дебаггер + Фикс Таблицы", page_icon="🕵️", layout="wide")

try:
    rules_data = get_rules_from_sheets()
except Exception as e:
    st.error("⚠️ Не удалось загрузить базу правил.")
    st.stop()

# --- САЙДБАР: РЕЖИМ ЭКСПЕРТА ---
expert_rules = [r for r in rules_data if str(r.get('Режим Эксперта', '')).strip().lower() in ['да', 'yes', '+', '1', 'true', 'истина']]

expert_mode_enabled = False
expert_overrides = {}

if expert_rules:
    with st.sidebar:
        st.header("🧠 Режим Эксперта")
        expert_mode_enabled = st.toggle("Включить ручной контроль")
        
        if expert_mode_enabled:
            st.info("Эти оценки имеют наивысший приоритет. Они заменят расчеты ИИ или скрипта.")
            for r in expert_rules:
                code = str(r.get('Код', '')).strip()
                name = str(r.get('Критерий', '')).strip()
                max_score = r.get('Балл', 1.0) 
                
                val = st.number_input(f"[{code}] {name} (Макс: {max_score})", min_value=0.0, max_value=max_score, value=0.0, step=0.1)
                expert_overrides[code] = val

st.title("🕵️ MAP100: AI-Аудитор (Версия 4.2 - Победа над gspread)")
st.markdown("Вставьте ссылку на компанию. Повторные проверки мгновенны (из кэша).")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

if st.button("🚀 Запустить аудит и диагностику", type="primary", use_container_width=True):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    elif "yandex" not in yandex_url.lower() and "ya.ru" not in yandex_url.lower():
        st.error("❌ Пожалуйста, введите корректную ссылку на Яндекс.Карты.")
    else:
        doc = init_google_sheets()
        
        with st.spinner("Анализируем данные..."):
            ai_rules_list = [
                r for r in rules_data 
                if str(r.get('Код', '')).strip() and 'ИИ' in str(r.get('Как считаем', ''))
            ]
            dynamic_rules = "".join([f"- [{r['Код']}] {r['Критерий']} (Макс {r['Балл']}): {r['Инструкция для ИИ']}\n" for r in ai_rules_list])

            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                python_score, python_details, python_scores_dict = calculate_python_scores(raw_yandex_data)
                clean_data = trim_for_ai(raw_yandex_data)
            except Exception as e:
                st.error(f"Ошибка сбора данных: {e}")
                st.stop()

            # ИСПРАВЛЕНО: Добавлен try для корректной работы except в конце файла
            try:
                SYSTEM_INSTRUCTION = f"""
                Ты — эксперт по локальному SEO. Мы проводим аудит карточки Яндекс.Бизнеса по 100-балльной системе MAP100.
                
                Автоматический скрипт УЖЕ проверил объективные параметры.
                Вот лог его проверки:
                {chr(10).join(python_details)}
                
                Твоя задача — проверить карточку ИСКЛЮЧИТЕЛЬНО по оставшимся смысловым правилам:
                {dynamic_rules}
                
                ВЕРНИ ОТВЕТ СТРОГО В ФОРМАТЕ JSON:
                {{
                    "company_name": "", 
                    "business_niche": "", 
                    "ai_criteria_scores": {{"КОД-1": 1.5, "ВЫВЕДИ_СЮДА_ВСЕ_КОДЫ_ИЗ_СПИСКА": 0.0}},
                    "detailed_report": "Общий аналитический вывод.", 
                    "action_plan": ["шаг 1", "шаг 2"]
                }}
                """
                
                model = genai.GenerativeModel(
                    model_name="gemini-flash-latest", 
                    system_instruction=SYSTEM_INSTRUCTION,
                    generation_config={"response_mime_type": "application/json", "temperature": 0.1}
                )

                prompt = f"Данные для аудита:\n{json.dumps(clean_data, ensure_ascii=False)}"
                response = model.generate_content(prompt)
                
                try:
                    raw_text = response.text.strip()
                    start_idx = raw_text.find('{')
                    end_idx = raw_text.rfind('}')
                    
                    if start_idx != -1 and end_idx != -1:
                        json_str = raw_text[start_idx:end_idx+1]
                        ai_report = json.loads(json_str)
                    else:
                        ai_report = json.loads(raw_text)
                except Exception as ai_e:
                    st.warning("⚠️ ИИ не смог проанализировать тексты (сработал фильтр). Применены только алгоритмические оценки.")
                    ai_report = {
                        "company_name": clean_data.get("title", "Без названия"),
                        "business_niche": "Не определена",
                        "ai_criteria_scores": {},
                        "detailed_report": "Текстовый анализ прерван из-за политики безопасности Google.",
                        "action_plan": ["Проверьте текст на стоп-слова."]
                    }
                
                st.success("✅ Анализ завершен!")
                
                # ========================================================
                # ДЕБАГГЕР: СБОР ИНФОРМАЦИИ И СЛИЯНИЕ БАЛЛОВ
                # ========================================================
                final_scores_dict = {}
                raw_ai_scores = ai_report.get('ai_criteria_scores', {})
                debug_logs = []
                
                for r in rules_data:
                    code = str(r.get('Код', '')).strip()
                    if not code: continue
                        
                    raw_sheet_val = r.get('DEBUG_RAW_SCORE', 'N/A')
                    max_score = r.get('Балл', 0.0) 
                    
                    py_val = python_scores_dict.get(code, "Нет")
                    ai_val = raw_ai_scores.get(code, "Нет")
                    current_val = 0.0
                    source_decision = "Не выполнено (0.0)"
                    
                    if py_val != "Нет":
                        current_val = min(float(py_val), max_score)
                        source_decision = f"Python (Обрезано: min({py_val}, {max_score}))"
                    elif ai_val != "Нет":
                        try:
                            ai_float = float(ai_val)
                            current_val = min(ai_float, max_score)
                            source_decision = f"Gemini (Обрезано: min({ai_float}, {max_score}))"
                        except Exception:
                            pass
                            
                    if expert_mode_enabled and code in expert_overrides:
                        current_val = expert_overrides[code]
                        source_decision = f"Ручной ввод (Эксперт)"
                        
                    final_scores_dict[code] = current_val
                    
                    debug_logs.append({
                        "Код": code,
                        "Критерий": r.get('Критерий', ''),
                        "Что отдал Google (Сырье)": str(raw_sheet_val),
                        "Лимит в коде": max_score,
                        "ИИ предложил": ai_val,
                        "ИТОГО": current_val,
                        "Вердикт": source_decision
                    })
                
                final_total_score = sum(final_scores_dict.values())
                
                # --- ИНТЕРФЕЙС ДЕБАГГЕРА ---
                st.divider()
                st.header("🚨 РЕЖИМ ГЛУБОКОГО ДЕБАГА (Версия 4.2)")
                
                anomalies = [d for d in debug_logs if float(d["ИТОГО"]) > 4.0]
                if anomalies:
                    st.error(f"⚠️ НАЙДЕНО {len(anomalies)} АНОМАЛИЙ (Балл выше 4.0). Читайте расследование ниже.")
                    for a in anomalies:
                        st.warning(f"**Аномалия в метрике {a['Код']}: ИТОГО = {a['ИТОГО']}**. Сырые данные таблицы: {a['Что отдал Google (Сырье)']}")
                else:
                    st.success("✅ Аномалий не найдено. Все лимиты и баллы работают идеально! Значения не превышают потолок.")

                with st.expander("🔬 ТЕХНИЧЕСКИЙ ЛОГ КАЖДОЙ ОЦЕНКИ (Таблица диагностики)", expanded=False):
                    st.dataframe(debug_logs, use_container_width=True)

                st.divider()
                
                # --- ФИНАЛЬНЫЙ ВЫВОД ---
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.subheader(f"🏢 {ai_report.get('company_name', 'Без названия')}")
                    st.caption(f"Ниша: {ai_report.get('business_niche', 'Не определена')}")
                with col2:
                    if final_total_score >= 80: color = "normal"
                    elif final_total_score >= 50: color = "off"
                    else: color = "inverse"
                    st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100", delta_color=color)

                with st.expander("📊 Детализация баллов по критериям (Нажмите для просмотра)"):
                    st.json(final_scores_dict)

                st.divider()
                st.markdown("### 🔍 Общий аналитический отчет")
                st.write(ai_report.get('detailed_report', 'Отчет пуст'))
                    
                st.markdown("### 🛠 Пошаговый план исправлений")
                for i, step in enumerate(ai_report.get('action_plan', [])):
                    st.info(f"**Шаг {i+1}:** {step}")

                # --- ЗАПИСЬ В GOOGLE ТАБЛИЦУ ---
                try:
                    results_sheet = doc.worksheet("Results")
                    headers = results_sheet.row_values(1)
                    
                    base_headers = ["Дата", "Ссылка", "Компания", "Ниша", "Общий балл"]
                    if not headers:
                        headers = base_headers
                    
                    headers_changed = False
                    for code in final_scores_dict.keys():
                        if code not in headers:
                            headers.append(code)
                            headers_changed = True
                    
                    if headers_changed:
                        cell_list = results_sheet.range(1, 1, 1, len(headers))
                        for i, val in enumerate(headers):
                            cell_list[i].value = val
                        results_sheet.update_cells(cell_list)

                    row_data = []
                    for h in headers:
                        if h == "Дата": row_data.append(time.strftime("%d.%m.%Y %H:%M:%S"))
                        elif h == "Ссылка": row_data.append(yandex_url)
                        elif h == "Компания": row_data.append(ai_report.get('company_name', ''))
                        elif h == "Ниша": row_data.append(ai_report.get('business_niche', ''))
                        elif h == "Общий балл": row_data.append(final_total_score)
                        else: row_data.append(final_scores_dict.get(h, 0.0))

                    results_sheet.append_row(row_data)
                except Exception as e:
                    st.warning("Не удалось сохранить в результаты (проверьте вкладку Results).")

            except Exception as e:
                st.error(f"⚠️ Ошибка на сервере ИИ: {e}")
