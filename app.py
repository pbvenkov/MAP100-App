def normalize_yandex_url(raw_url):
    """Очищает ссылку от параметров поиска и вкладок, сохраняя структуру карточки"""
    url = raw_url.strip()
    
    # Разворачиваем короткие ссылки (/-/CT...)
    if "/-/" in url:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            res = requests.get(url, headers=headers, allow_redirects=True, timeout=10)
            url = res.url
        except Exception:
            pass

    # Заменяем навигатор на карты
    url = url.replace("yandex.ru/navi/", "yandex.ru/maps/").replace("yandex.com/navi/", "yandex.com/maps/")
    
    # Отрезаем GET-параметры (?ll=..., &sctx=...)
    if "?" in url:
        url = url.split("?")[0]
        
    # Убираем вложенные вкладки (/reviews, /gallery, /menu, /features)
    url = re.sub(r'/(reviews|gallery|features|menu|goods)/?$', '', url)
    
    # Добавляем закрывающий слэш
    return url.rstrip('/') + '/'

def fetch_apify_data(yandex_url):
    cleaned_url = normalize_yandex_url(yandex_url)
    
    # В payload передаем ТОЛЬКО startUrls (без searchStrings)
    run_req = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}",
        json={
            "startUrls": [{"url": cleaned_url}],
            "maxItems": 1,
            "enrichBusinessData": True,
            "maxPhotos": 80,
            "maxPosts": 30
        },
        timeout=15
    ).json()
    
    if 'error' in run_req: 
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: 
            raise Exception("Таймаут сбора данных. Яндекс долго отвечает.")
        time.sleep(4)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", timeout=10).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": 
        raise Exception(f"Парсер завершился со статусом {status}.")
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", timeout=15).json()
    
    if not dataset or not isinstance(dataset, list) or len(dataset) == 0 or not dataset[0].get('title'): 
        raise Exception(f"Яндекс не вернул данные по адресу: {cleaned_url}")
        
    return dataset[0]
