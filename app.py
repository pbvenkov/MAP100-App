import streamlit as st
import requests
import time
import json
import numpy as np
import pandas as pd
import re
import itertools
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Настройка Gemini AI
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден или настроен неверно. AI-функции будут отключены.")
    ai_model = None

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
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    
    for r in records:
        raw_val = r.get('Балл', 0.0)
        try:
            if isinstance(raw_val, (int, float)): r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError:
            r['Балл'] = 0.0
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
# 3. МОДУЛЬНАЯ АРХИТЕКТУРА (Алгоритмы + AI)
# ==========================================

def calculate_prof_rules(data):
    scores, logs = {}, []
    has_blue_tick = data.get('isVerifiedOwner', False)
    if has_blue_tick:
        scores['PROF-12.1'] = True
        scores['PROF-01.1'] = True
        scores['PROF-03.1'] = True
        scores['PROF-05.1'] = True
        scores['PROF-07.1'] = True
        logs.append("✅ [PROF-12.1] Синяя галочка (Верифицированный владелец) подтверждена.")
        logs.append("✅ [PROF-01.1] Название заполнено (Засчитано авто-галочкой).")
        logs.append("✅ [PROF-03.1] Категории указаны (Засчитано авто-галочкой).")
        logs.append("✅ [PROF-05.1] Основной телефон есть (Засчитано авто-галочкой).")
        logs.append("✅ [PROF-07.1] График работы заполнен (Засчитано авто-галочкой).")
    else:
        if len(data.get('title', '')) > 2: scores['PROF-01.1'] = True
        if len(data.get('categories') or []) > 0: scores['PROF-03.1'] = True
        if data.get('phones'): scores['PROF-05.1'] = True
        if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = True

    if data.get('phones') and any("доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10 for p in data.get('phones')):
        scores['PROF-05.2'] = True
    if data.get('features') and len(data['features']) > 0: scores['PROF-08.1'] = True
    desc = data.get('description') or ''
    if len(desc) > 1500: scores['PROF-10.1'] = True
    website = data.get('url') or data.get('website') or ''
    if website: 
        scores['PROF-04.1'] = True
        if "utm_" in str(website).lower(): scores['PROF-04.2'] = True
    if data.get('requisites') or data.get('legalInfo'): 
        scores['PROF-15.1'] = True
        logs.append("✅ [PROF-15.1] Заполнена вкладка с юридическими данными (реквизиты).")

    schedule_str = str(data.get('workingHours') or data.get('schedule') or '').lower()
    if "перерыв" in schedule_str or "special" in schedule_str or "intervals" in schedule_str: scores['PROF-07.2'] = True

    desc_and_features = (desc + " " + " ".join(str(f).lower() for f in (data.get('features') or []))).lower()
    if re.search(r'(основан[а-я]? в 19\d{2}|основан[а-я]? в 20\d{2}|работает с 19\d{2}|работает с 20\d{2}|since 19\d{2}|since 20\d{2})', desc_and_features):
        scores['PROF-14.1'] = True

    products = (data.get('menu') or {}).get('items') or data.get('productCatalog') or []
    if len(products) >= 10:
        scores['PROF-11.1'] = True
        with_photo = sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image'))
        with_price = sum(1 for p in products if p.get('price'))
        with_desc = sum(1 for p in products if len(str(p.get('description') or '')) > 50)
        categories_set = set(p['category'].get('name') if isinstance(p.get('category'), dict) else p.get('category') for p in products if p.get('category'))
        
        if (with_photo / len(products)) >= 0.8: scores['PROF-11.2'] = True
        if (with_price / len(products)) >= 0.8: scores['PROF-11.3'] = True
        if (with_desc / len(products)) >= 0.8: scores['PROF-11.4'] = True
        if len(categories_set) >= 2: scores['PROF-11.5'] = True
            
    links_str = " ".join(str(l).lower() for l in (data.get('links') or []) + (data.get('socials') or []))
    if any(s in links_str for s in ["t.me", "tg://", "wa.me", "whatsapp"]): scores['PROF-13.1'] = True
    if any(s in links_str for s in ["vk.com", "youtube", "dzen"]): scores['PROF-13.2'] = True

    return scores, logs

def calculate_cont_rules(data):
    scores, logs = {}, []
    photo_count = data.get('photoCount') or data.get('photosCount') or 0
    if photo_count >= 15: scores['CONT-36.1'] = True
    if photo_count >= 30: scores['CONT-36.2'] = True
    if len(data.get('stories') or data.get('storyUrls') or []) > 0: 
        scores['CONT-44.1'] = True
        logs.append("✅ [CONT-44.1] В карточке найдены Истории (Stories).")
    if data.get('panoramaUrl') or data.get('panoramas') or len(data.get('videos') or []) > 0: 
        scores['CONT-42.1'] = True
        logs.append("✅ [CONT-42.1] Найдено видео или 3D-панорама.")
    for p in (data.get('photos') or data.get('images') or []):
        if any(kw in str(p).lower() for kw in ['внутри', 'интерьер', 'interior', 'inside', 'залы']):
            scores['CONT-43.1'] = True
            logs.append("✅ [CONT-43.1] В галерее найдены фотографии категории 'Интерьер/Внутри'.")
            break
    return scores, logs

def calculate_rep_rules(data):
    scores, logs = {}, []
    rating = data.get('rating') or 0.0
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    if (data.get('reviewsCount') or data.get('ratingsCount') or 0) >= 50: scores['REP-28.1'] = True
    
    reviews = data.get('reviews') or []
    if reviews:
        first_rev_date_str = reviews[0].get('date') or reviews[0].get('createdAt')
        if first_rev_date_str:
            try:
                rev_date = datetime.fromisoformat(first_rev_date_str.replace('Z', '+00:00'))
                if (datetime.now(rev_date.tzinfo) - rev_date).days < 14: scores['REP-29.1'] = True
            except: pass
                
        last_20_reviews = reviews[:20]
        replied_count, total_days, valid_times = 0, 0, 0
        unanswered_negative, answered_positive = 0, 0
        owner_texts = []
        
        with_photo = sum(1 for r in last_20_reviews if r.get('photos') or r.get('images'))
        if len(last_20_reviews) > 0 and (with_photo / len(last_20_reviews)) >= 0.1: 
            scores['REP-35.1'] = True
            logs.append(f"✅ [REP-35.1] Доля отзывов с фото более 10% ({with_photo} шт).")
        
        for rev in last_20_reviews:
            r_rating = rev.get('rating') or 0
            reply = rev.get('reply') or rev.get('ownerAnswer')
            if reply:
                replied_count += 1
                if reply.get('text'): owner_texts.append(reply.get('text').lower())
                d1 = rev.get('date') or rev.get('createdAt')
                d2 = reply.get('date') or reply.get('createdAt') or reply.get('updatedAt')
                if d1 and d2:
                    try:
                        r_d = datetime.fromisoformat(d1.replace('Z', '+00:00'))
                        a_d = datetime.fromisoformat(d2.replace('Z', '+00:00'))
                        if (a_d - r_d).days >= 0:
                            total_days += (a_d - r_d).days
                            valid_times += 1
                    except: pass
            if r_rating <= 3 and not reply: unanswered_negative += 1
            if r_rating >= 4 and reply: answered_positive += 1
        
        if len(last_20_reviews) > 0 and (replied_count / len(last_20_reviews)) >= 0.9: 
            scores['REP-30.1'] = True
            logs.append("✅ [REP-30.1] Владелец ответил на 90% и более из последних 20 отзывов.")
        if valid_times > 0 and (total_days / valid_times) <= 3: 
            scores['REP-30.2'] = True
            logs.append("✅ [REP-30.2] Средняя скорость ответа <= 3 дней.")
        if unanswered_negative == 0 and len(last_20_reviews) > 0: 
            scores['REP-32.1'] = True
            logs.append("✅ [REP-32.1] Нет брошенного негатива (на все оценки 1-3 звезды дан ответ).")
        if answered_positive > 0: 
            scores['REP-30.3'] = True
            
        if len(owner_texts) >= 2:
            is_templated = False
            for t1, t2 in itertools.combinations(owner_texts[:10], 2):
                s1, s2 = set(re.findall(r'\w+', t1)), set(re.findall(r'\w+', t2))
                if len(s1 | s2) > 0 and (len(s1 & s2) / len(s1 | s2)) > 0.8:
                    is_templated = True; break
            if not is_templated: 
                scores['REP-31.1'] = True
                logs.append("✅ [REP-31.1] Тексты ответов уникальны (не скопированы).")
        elif len(owner_texts) == 1: scores['REP-31.1'] = True

    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    links_str = " ".join(str(l).lower() for l in (data.get('links') or []) + (data.get('socials') or []))
    features_str = " ".join(str(f).lower() for f in (data.get('features') or []))
    
    if any(b in links_str or b in features_str for b in ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн', 'nethouse']):
        scores['CONV-48.1'] = True
        logs.append("✅ [CONV-48.1] Найдена система онлайн-записи.")
    if "chat" in features_str or data.get('isChatEnabled') == True: scores['CONV-50.1'] = True
    if len(data.get('posts') or data.get('news') or data.get('promos') or []) > 0: scores['CONV-51.1'] = True
    if data.get('actionUrl') or data.get('bookingUrl'): 
        scores['CONV-47.1'] = True
        logs.append("✅ [CONV-47.1] Настроена главная кнопка действия (actionUrl).")
    if len(data.get('questionsAndAnswers') or data.get('faq') or data.get('qna') or []) > 0: 
        scores['CONV-52.1'] = True
        logs.append("✅ [CONV-52.1] Заполнен блок FAQ (Вопросы и ответы).")
        
    for p in ((data.get('menu') or {}).get('items') or data.get('productCatalog') or []):
        if p.get('oldPrice') or p.get('discount') or any(kw in str(p).lower() for kw in ['хит', 'новинка', 'скидка', 'акция']):
            scores['CONV-53.1'] = True
            logs.append("✅ [CONV-53.1] В товарах найдены бейджи (Хит, Скидка и т.д.).")
            break
    return scores, logs

def calculate_seo_rules(data):
    scores, logs = {}, []
    if len(data.get('address') or '') > 5: scores['SEO-18.1'] = True
    areas = data.get('serviceArea') or data.get('deliveryArea')
    if areas or any(k in str(data.get('features') or []).lower() for k in ['выезд', 'доставк', 'зона обслуживани', 'радиус']):
        scores['SEO-18.2'] = True
    return scores, logs

def calculate_act_rules(data):
    scores, logs = {}, []
    fresh_found, now_utc = False, datetime.now(timezone.utc)
    for p in data.get('posts', []) + data.get('news', []) + data.get('promos', []):
        d_str = p.get('date') or p.get('publishedAt') or p.get('createdAt')
        if d_str:
            try:
                if (now_utc - datetime.fromisoformat(d_str.replace('Z', '+00:00'))).days <= 30: fresh_found = True; break
            except: pass
    if not fresh_found and (data.get('stories') or data.get('storyUrls')): fresh_found = True
    if fresh_found: 
        scores['ACT-68.1'] = True
        logs.append("✅ [ACT-68.1] Найдена свежая активность (<30 дней).")
    if data.get('isAdvertiser') or data.get('advertiser'): 
        scores['ACT-69.1'] = True
        logs.append("✅ [ACT-69.1] Карточка оплатила Приоритетное размещение (зеленая метка).")
    return scores, logs

def calculate_ai_rules(data):
    scores, logs = {}, []
    description = data.get('description', '')
    
    if not description or not ai_model:
        return scores, logs
        
    prompt = f"""
    Проанализируй описание профиля компании и ответь на 4 вопроса строго в формате JSON.
    Текст описания: "{description}"

    Вопросы:
    1. PROF-10.6: Присутствует ли в тексте явный призыв к действию (CTA)? Например: звоните, приходите, записывайтесь, переходите на сайт.
    2. PROF-10.3: Перечислены ли конкретные услуги компании, или текст написан только общими хвалебными фразами? (true - если услуги перечислены).
    3. CONV-49.1: Содержит ли первый абзац (первые 200 символов) сильное, понятное Уникальное Торговое Предложение (УТП)? Сразу ли понятно, чем они выделяются?
    4. SEO-18.3: Есть ли в тексте названия конкретных городов, районов, улиц или станций метро (топонимы)?

    Верни ТОЛЬКО валидный JSON объект с булевыми значениями (true или false), без дополнительных символов или форматирования Markdown:
    {{
      "PROF-10.6": true,
      "PROF-10.3": true,
      "CONV-49.1": false,
      "SEO-18.3": true
    }}
    """
    
    try:
        response = ai_model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        ai_result = json.loads(raw_text)
        
        if ai_result.get("PROF-10.6"): 
            scores["PROF-10.6"] = True
            logs.append("✅ [PROF-10.6] AI: Нашел явный призыв к действию (CTA).")
        if ai_result.get("PROF-10.3"): 
            scores["PROF-10.3"] = True
            logs.append("✅ [PROF-10.3] AI: Услуги конкретно перечислены в тексте.")
        if ai_result.get("CONV-49.1"): 
            scores["CONV-49.1"] = True
            logs.append("✅ [CONV-49.1] AI: В первом абзаце найдено сильное УТП.")
        if ai_result.get("SEO-18.3"): 
            scores["SEO-18.3"] = True
            logs.append("✅ [SEO-18.3] AI: Нашел топонимы (города/районы) в тексте.")
            
    except Exception as e:
        logs.append(f"⚠️ [AI-Ошибка] Не удалось проанализировать текст через Gemini: {e}")
        
    return scores, logs


def calculate_all_python_rules(data):
    all_scores, all_logs = {}, []
    mods = [
        calculate_prof_rules(data),
        calculate_cont_rules(data),
        calculate_rep_rules(data),
        calculate_conv_rules(data),
        calculate_seo_rules(data),
        calculate_act_rules(data),
        calculate_ai_rules(data)
    ]
    for s_dict, l_list in mods:
        all_scores.update(s_dict)
        all_logs.extend(l_list)
    return all_scores, all_logs

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Нейро-Аудитор", page_icon="🧠", layout="wide")

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
            val = st.number_input(f"[{code}] {name}", min_value=0.0, max_value=max_score, value=0.0, step=0.5, help=str(r.get('Инструкция по вычислению', '')))
            manual_overrides[code] = val

# --- ОСНОВНОЙ ЭКРАН ---
st.title("📍 MAP100: AI-Аудитор (Версия 7.1 - Красивые Отчеты)")

stat_python = sum(1 for r in rules_data if r.get('Статус') == "Python")
stat_manual = sum(1 for r in rules_data if r.get('Статус') == "Ручной")
stat_stub = sum(1 for r in rules_data if r.get('Статус') not in ["Python", "Ручной"] and str(r.get('Код', '')).strip())

col_s1, col_s2, col_s3 = st.columns(3)
col_s1.metric("🟢 Готово (Python+AI)", stat_python)
col_s2.metric("🧠 Ручной режим", stat_manual)
col_s3.metric("🟡 В разработке (Заглушки)", stat_stub)
st.divider()

yandex_url = st.text_input("Ссылка на карточку Яндекс.Бизнеса")

if st.button("🚀 Запустить аудит", type="primary", use_container_width=True):
    if not yandex_url or "yandex" not in yandex_url.lower():
        st.error("❌ Введите корректную ссылку на Яндекс.Карты.")
    else:
        doc = init_google_sheets()
        with st.spinner("Синтезирую данные: парсер + ИИ анализирует тексты..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                company_name = raw_yandex_data.get('title', 'Без названия')
                python_scores_dict, python_logs = calculate_all_python_rules(raw_yandex_data)
            except Exception as e:
                st.error(f"Ошибка: {e}")
                st.stop()
                
            final_scores_dict = {}
            detailed_results = []
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                
                name = str(r.get('Критерий', '')).strip()
                max_score = float(r.get('Балл', 0.0))
                status = r.get('Статус', 'Заглушка')
                instruction = str(r.get('Инструкция по вычислению', ''))
                
                current_val = 0.0
                if status == "Python" and python_scores_dict.get(code):
                    current_val = max_score 
                elif status == "Ручной" and code in manual_overrides:
                    current_val = min(float(manual_overrides[code]), max_score)
                
                final_scores_dict[code] = current_val
                
                # --- ГЕНЕРАЦИЯ КОММЕНТАРИЯ ДЛЯ ТАБЛИЦЫ ---
                comment = ""
                if status == "Python":
                    specific_log = None
                    # Ищем красивый лог от скрипта
                    for log in python_logs:
                        if f"[{code}]" in log:
                            parts = log.split("]", 1)
                            if len(parts) > 1:
                                specific_log = parts[1].strip()
                                break
                    
                    if current_val > 0:
                        if specific_log:
                            comment = "✅ " + specific_log
                        else:
                            comment = "✅ " + (instruction if instruction else "Условие выполнено")
                    else:
                        comment = "❌ Не выполнено / Данные отсутствуют"
                elif status == "Ручной":
                    if current_val > 0:
                        comment = f"🧠 Оценено вручную экспертом"
                    else:
                        comment = "⚪ Не оценивалось (0 баллов)"
                else:
                    comment = "🟡 В разработке (Заглушка)"
                    
                detailed_results.append({
                    "Код": code,
                    "Критерий": name,
                    "Балл": current_val,
                    "Макс": max_score,
                    "Комментарий": comment
                })
                
            final_total_score = sum(final_scores_dict.values())
            
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1: st.subheader(f"🏢 {company_name}")
            with col2:
                color = "normal" if final_total_score >= 80 else ("off" if final_total_score >= 50 else "inverse")
                st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100", delta_color=color)

            # --- ВЫВОД КРАСИВОЙ ТАБЛИЦЫ ВМЕСТО СУХОГО JSON ---
            with st.expander("📊 Детализация баллов по критериям", expanded=True):
                st.dataframe(
                    pd.DataFrame(detailed_results),
                    column_config={
                        "Код": st.column_config.TextColumn("Код", width="small"),
                        "Критерий": st.column_config.TextColumn("Критерий", width="medium"),
                        "Балл": st.column_config.NumberColumn("Балл", format="%.1f"),
                        "Макс": st.column_config.NumberColumn("Макс.", format="%.1f"),
                        "Комментарий": st.column_config.TextColumn("Комментарий (Почему так)", width="large"),
                    },
                    hide_index=True,
                    use_container_width=True
                )

            # Для дебага оставили логи скрытыми внизу
            with st.expander("🛠️ Системные логи (Отладка)", expanded=False):
                for log in python_logs: st.write(log)

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
# 5. СЕРВИСНАЯ ПАНЕЛЬ ДЛЯ РАЗРАБОТЧИКА
# ==========================================
st.divider()
st.subheader("🛠 Сервисная панель разработчика")

col_btn1, col_btn2 = st.columns(2)

with col_btn1:
    if st.button("🪄 1. Разметка статусов"):
        with st.spinner("Расставляю статусы..."):
            try:
                doc = init_google_sheets()
                sheet = doc.worksheet("Rules")
                headers = sheet.row_values(1)
                
                col_idx = headers.index("Статус") + 1 if "Статус" in headers else len(headers) + 1
                
                records = sheet.get_all_records()
                python_codes = [
                    "PROF-01.1", "PROF-03.1", "PROF-05.1", "PROF-05.2", "PROF-07.1", "PROF-08.1", "PROF-11.1", 
                    "PROF-11.2", "PROF-11.3", "PROF-11.4", "PROF-11.5", "PROF-12.1", "PROF-13.1", "PROF-13.2", 
                    "CONT-36.1", "CONT-36.2", "REP-27.1", "REP-27.2", "REP-28.1", "CONV-48.1", "CONV-50.1", 
                    "PROF-04.1", "PROF-04.2", "PROF-10.1", "SEO-18.1", "CONT-44.1", "CONT-42.1", "CONV-51.1", 
                    "CONV-47.1", "PROF-15.1", "REP-29.1", "REP-30.1", "REP-30.2", "CONV-52.1", "PROF-07.2", 
                    "SEO-18.2", "CONT-43.1", "REP-32.1", "REP-30.3", "REP-31.1", "CONV-53.1", "PROF-14.1",
                    "ACT-68.1", "REP-35.1", "ACT-69.1", 
                    "PROF-10.6", "PROF-10.3", "CONV-49.1", "SEO-18.3"
                ]
                
                cell_list = sheet.range(2, col_idx, len(records) + 1, col_idx)
                for i, row in enumerate(records):
                    code = str(row.get('Код', '')).strip()
                    how = str(row.get('Как считаем', '')).strip().lower()
                    if code in python_codes: cell_list[i].value = "Python"
                    elif "ии" in how or "ручн" in how or "эксперт" in str(row.get('Режим Эксперта', '')).lower():
                        cell_list[i].value = "Ручной"
                    else: cell_list[i].value = "Заглушка"
                        
                sheet.update_cells(cell_list)
                st.success("✅ Статусы обновлены! ИИ-метрики теперь автоматизированы.")
            except Exception as e: st.error(f"Ошибка: {e}")

with col_btn2:
    if st.button("📝 2. Записать инструкции ИИ"):
        with st.spinner("Записываю логику нейросети..."):
            try:
                doc = init_google_sheets()
                sheet = doc.worksheet("Rules")
                headers = sheet.row_values(1)
                
                col_idx = headers.index("Инструкция по вычислению") + 1 if "Инструкция по вычислению" in headers else len(headers) + 1
                
                records = sheet.get_all_records()
                logic_dict = {
                    "PROF-10.6": "AI (Gemini) читает текст описания и ищет явный призыв к действию (Звоните, переходите на сайт).",
                    "PROF-10.3": "AI (Gemini) проверяет, перечислены ли конкретные услуги компании, а не просто хвалебная вода.",
                    "CONV-49.1": "AI (Gemini) анализирует первый абзац текста на наличие сильного Уникального Торгового Предложения (УТП).",
                    "SEO-18.3": "AI (Gemini) ищет в описании топонимы (названия городов, районов, улиц, метро)."
                }
                
                cell_list = sheet.range(2, col_idx, len(records) + 1, col_idx)
                for i, row in enumerate(records):
                    code = str(row.get('Код', '')).strip()
                    if code in logic_dict: cell_list[i].value = logic_dict[code]
                    else: cell_list[i].value = str(row.get('Инструкция по вычислению', ''))
                        
                sheet.update_cells(cell_list)
                st.success("✅ Логика ИИ записана в таблицу!")
                st.balloons()
            except Exception as e: st.error(f"Ошибка: {e}")
