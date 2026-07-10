import streamlit as st
import requests
import time
import json
import numpy as np
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
# 2. КЭШИРОВАННЫЕ БАЗОВЫЕ ФУНКЦИИ
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

@st.cache_data(ttl=60, show_spinner=False)
def get_rules_from_sheets():
    """Читает правила один раз в минуту, чтобы интерфейс работал быстро."""
    doc = init_google_sheets()
    return doc.worksheet("Rules").get_all_records()

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
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        time.sleep(5)
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}"
        status = requests.get(status_url).json()['data']['status']

    if status != "SUCCEEDED":
        raise Exception("Ошибка при парсинге данных Apify.")

    dataset_url = f"https://api.apify.com/v2/datasets/{default_dataset_id}/items?token={APIFY_API_TOKEN}"
    dataset_req = requests.get(dataset_url).json()
    
    if not dataset_req:
        raise Exception("Парсер не нашел данных.")
        
    return dataset_req[0]

# ==========================================
# 3. ГИБРИДНАЯ АРХИТЕКТУРА: PYTHON
# ==========================================
def calculate_python_scores(data):
    """Считает баллы по объективным метрикам без ИИ."""
    scores = {}
    details = []

    if len(data.get('title', '')) > 2:
        scores['PROF-01.1'] = 0.5
        
    if len(data.get('phones', [])) > 0:
        scores['PROF-05.1'] = 1.0

    if len(data.get('schedule', [])) == 7:
        scores['PROF-07.1'] = 1.0

    if data.get('isVerifiedOwner') == True:
        scores['PROF-12.1'] = 3.0
        details.append("✅ [PROF-12.1] Аккаунт верифицирован (Синяя галочка) (+3.0)")
    else:
        details.append("❌ [PROF-12.1] Отсутствует Синяя галочка (0.0)")

    photo_count = data.get('photoCount', 0)
    if photo_count >= 15:
        scores['CONT-36.1'] = 1.5
        if photo_count >= 30:
            scores['CONT-36.2'] = 1.0
        details.append(f"✅ [CONT-36] Хорошая галерея: {photo_count} фото.")
    else:
        details.append(f"❌ [CONT-36] Мало фото: {photo_count} (нужно от 15).")

    products = data.get('menu', {}).get('items', [])
    if not products:
        products = data.get('productCatalog', [])
        
    if len(products) >= 10:
        scores['PROF-11.1'] = 1.5
        details.append(f"✅ [PROF-11.1] Каталог заполнен: {len(products)} позиций (+1.5)")
    else:
        details.append(f"❌ [PROF-11.1] Мало товаров/услуг в каталоге: {len(products)} из 10.")

    rating = data.get('rating', 0)
    if rating >= 4.8:
        scores['REP-27.2'] = 2.0
        scores['REP-27.1'] = 2.0
    elif rating >= 4.5:
        scores['REP-27.1'] = 2.0

    reviews_count = data.get('ratingsCount', 0)
    if reviews_count >= 50:
        scores['REP-28.1'] = 2.0

    reviews_data = data.get('reviews', [])
    response_times = []
    
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
        else:
            details.append(f"❌ [REP-30.2] Медленные ответы: {median_speed} дн. (норма < 3).")

    return sum(scores.values()), details, scores

def trim_for_ai(raw_data):
    """Сжимает профиль Яндекса до текстовой выжимки для Gemini."""
    trimmed = {
        "title": raw_data.get("title", ""),
        "description": raw_data.get("description", ""),
        "categories": raw_data.get("categories", []),
        "features": list(raw_data.get("features", {}).keys()),
        "products": [],
        "reviews": []
    }
    
    products = raw_data.get('menu', {}).get('items', [])
    if products:
        trimmed["products"] = [p.get("title", "") for p in products[:15]]
    
    for r in raw_data.get("reviews", [])[:10]:
        trimmed["reviews"].append({
            "text": r.get("text", ""),
            "rating": r.get("rating", ""),
            "owner_reply": r.get("businessComment", "")
        })
    return trimmed

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Гибридный Аудит", page_icon="📍", layout="wide")

try:
    rules_data = get_rules_from_sheets()
except Exception as e:
    st.error("⚠️ Не удалось загрузить базу правил из Google Таблицы.")
    st.stop()

# --- САЙДБАР: РЕЖИМ ЭКСПЕРТА (АДМИНКА ИЗ ТАБЛИЦЫ) ---
expert_rules = [r for r in rules_data if str(r.get('Режим Эксперта', '')).strip().lower() in ['да', 'yes', '+', '1', 'true']]

expert_mode_enabled = False
expert_overrides = {}

if expert_rules:
    with st.sidebar:
        st.header("🧠 Режим Эксперта")
        expert_mode_enabled = st.toggle("Включить ручной контроль")
        
        if expert_mode_enabled:
            st.info("Эти оценки имеют наивысший приоритет. Они заменят любые расчеты ИИ или скрипта.")
            for r in expert_rules:
                code = str(r.get('Код', '')).strip()
                name = str(r.get('Критерий', '')).strip()
                try:
                    max_score = float(str(r.get('Балл', '0')).replace(',', '.'))
                except Exception:
                    max_score = 1.0
                
                # Создаем числовое поле ввода для каждой метрики
                val = st.number_input(f"[{code}] {name} (Макс: {max_score})", min_value=0.0, max_value=max_score, value=0.0, step=0.1)
                expert_overrides[code] = val


st.title("📍 MAP100: AI-Аудитор Яндекс.Бизнеса")
st.markdown("Вставьте ссылку на компанию. Повторные проверки мгновенны (из кэша).")

yandex_url = st.text_input("Ссылка на карточку (например: https://yandex.ru/maps/org/...)")

col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    if st.button("🛠 Скачать сырой JSON", type="secondary"):
        if yandex_url:
            with st.spinner("Забираем данные..."):
                raw = fetch_apify_data(yandex_url) 
                st.download_button(
                    label="📥 Скачать yandex_raw_data.json",
                    file_name="yandex_raw_data.json",
                    mime="application/json",
                    data=json.dumps(raw, ensure_ascii=False, indent=4),
                )
        else:
            st.warning("Сначала введите ссылку выше.")

with col_btn2:
    if st.button("🛠 Узнать РАБОЧИЕ модели", type="secondary"):
        with st.spinner("Простукиваем серверы Google..."):
            working_models = []
            try:
                for m in genai.list_models():
                    if 'generateContent' in m.supported_generation_methods:
                        model_name = m.name.replace('models/', '')
                        try:
                            test_model = genai.GenerativeModel(model_name)
                            test_model.generate_content("1")
                            working_models.append(model_name)
                        except Exception:
                            pass 
                
                if working_models:
                    st.success("✅ Работают:")
                    st.write(working_models)
                else:
                    st.error("Ни одна модель не пропустила запрос.")
            except Exception as e:
                st.error(f"Ошибка проверки: {e}")

st.divider()

if st.button("🚀 Запустить аудит", type="primary", use_container_width=True):
    if not yandex_url:
        st.warning("Пожалуйста, введите ссылку.")
    else:
        doc = init_google_sheets()
        
        with st.spinner("Шаг 0: Читаем правила ИИ из базы..."):
            ai_rules_list = [
                r for r in rules_data 
                if str(r.get('Код', '')).strip() and 'ИИ' in str(r.get('Как считаем', ''))
            ]
            dynamic_rules = "".join([f"- [{r['Код']}] {r['Критерий']} (Макс {r['Балл']}): {r['Инструкция для ИИ']}\n" for r in ai_rules_list])

        with st.spinner("Шаг 1: Python анализирует объективные данные..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                python_score, python_details, python_scores_dict = calculate_python_scores(raw_yandex_data)
                clean_data = trim_for_ai(raw_yandex_data)
                
            except Exception as e:
                st.error(f"Ошибка сбора данных: {e}")
                st.stop()

        with st.spinner("Шаг 2: Gemini анализирует тексты, SEO и смыслы..."):
            try:
                SYSTEM_INSTRUCTION = f"""
                Ты — эксперт по локальному SEO. Мы проводим аудит карточки Яндекс.Бизнеса по 100-балльной системе MAP100.
                
                Автоматический скрипт УЖЕ проверил объективные параметры и начислил {python_score} баллов.
                Вот лог его проверки:
                {chr(10).join(python_details)}
                
                Твоя задача — проверить карточку ИСКЛЮЧИТЕЛЬНО по оставшимся смысловым правилам:
                {dynamic_rules}
                
                КРИТИЧЕСКИ ВАЖНОЕ ПРАВИЛО ДЛЯ JSON:
                В словаре "ai_criteria_scores" ты ОБЯЗАН перечислить ВСЕ ДО ЕДИНОГО коды из списка правил выше.
                Если у тебя нет данных для оценки или критерий не выполнен, ставь строго 0.0.
                
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
                
                raw_text = response.text.strip()
                start_idx = raw_text.find('{')
                
                if start_idx != -1:
                    try:
                        json_to_decode = raw_text[start_idx:]
                        ai_report, idx = json.JSONDecoder().raw_decode(json_to_decode)
                    except Exception:
                        ai_report = json.loads(raw_text)
                else:
                    ai_report = json.loads(raw_text)
                
                st.success("✅ Анализ завершен!")
                
                # --- УМНОЕ СЛИЯНИЕ БАЛЛОВ С УЧЕТОМ ЭКСПЕРТА ---
                all_scores = {}
                
                # 1. Всем 95 метрикам ставим 0
                for r in rules_data:
                    code = str(r.get('Код', '')).strip()
                    if code:
                        all_scores[code] = 0.0
                
                # 2. Накатываем оценки Скрипта
                all_scores.update(python_scores_dict)
                
                # 3. Накатываем оценки ИИ
                all_scores.update(ai_report.get('ai_criteria_scores', {}))
                
                # 4. РЕЖИМ ЭКСПЕРТА: Перезаписываем ручными оценками
                if expert_mode_enabled:
                    for code, manual_val in expert_overrides.items():
                        all_scores[code] = manual_val
                
                # 5. Считаем реальный, выверенный Итоговый Балл
                final_total_score = sum(all_scores.values())
                
                # --- ВЫВОД НА ЭКРАН ---
                st.divider()
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
                    st.json(all_scores)

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
                    for code in all_scores.keys():
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
                        else: row_data.append(all_scores.get(h, 0.0))

                    results_sheet.append_row(row_data)
                    st.toast('Детальный отчет сохранен в Google Таблицу!', icon='💾')
                except Exception as e:
                    st.warning(f"Ошибка записи в таблицу: {e}")

            except Exception as e:
                st.error(f"⚠️ Ошибка связи с ИИ: {e}")
