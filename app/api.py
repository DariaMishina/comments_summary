from fastapi import APIRouter, HTTPException
from datetime import datetime
import pandas as pd
import nltk
from pydantic import BaseModel

from models import text_preproc, get_representative_texts, get_summary, kw_counter
from tasks import run_model_inference  #TODO - сейчас просто такая же логика как в обычных эндпоинтах только в одном месте(саммари + ключевые), надо придумать что-то еще для очереди)
# from database import log_request  

router = APIRouter()

class TextRequest(BaseModel):
    text: str

def load_stop_words():
    """
    Загружает список стоп-слов из CSV и nltk.
    Если CSV не найден, используется только nltk.
    """
    try:
        stop_words_csv = pd.read_csv('src/stop_words.csv')['word'].to_list()
    except Exception:
        stop_words_csv = []
    stop_words_nltk = nltk.corpus.stopwords.words("russian")
    return set(stop_words_csv + stop_words_nltk)

def split_reviews(text: str):
    """
    Разбивает входной текст на список отзывов по переводам строки.
    Отфильтровывает пустые строки.
    """
    reviews = [line.strip() for line in text.splitlines() if line.strip()]
    if not reviews:
        raise ValueError("Не удалось выделить ни одного отзыва из входного текста")
    return reviews

@router.get("/ping")
async def ping():
    return "Привет! Я микросервис и я живой."

@router.post("/summarize")
async def summarize_endpoint(request: TextRequest):
    """
    Эндпоинт для получения краткого суммарного описания отзывов.

    Входные данные:
      - text: строка, содержащая отзывы (каждый отзыв — с новой строки)

    Логика:
      1. Разбивает входной текст на список отзывов.
      2. Загружает стоп-слова.
      3. Для каждого отзыва получает лемматизированный вариант с помощью text_preproc.
      4. Пытается вычислить репрезентативные отзывы с помощью get_representative_texts.
         Если возникает ошибка, берутся первые 15 отзывов.
      5. Вызывается функция get_summary для получения суммарного описания.
      6. Логируется успешный вызов или ошибка в БД.
    """
    if not request.text:
        raise HTTPException(status_code=400, detail="Параметр 'text' не может быть пустым.")

    try:
        reviews = split_reviews(request.text)
        stop_words = load_stop_words()

        # получаем лемматизированную версию каждого отзыва
        lemmas = [text_preproc(review, stop_words=stop_words) for review in reviews]

        # пытаемся выделить репрезентативные отзывы (при небольшом числе отзывов функция вернёт исходный список)
        try:
            rep_reviews = get_representative_texts(lemmas, reviews)
        except Exception as err:
            # если не удалось получить репрезентативные отзывы — берём первые 5 отзывов
            rep_reviews = reviews[:5]

        summary = get_summary(rep_reviews)

        # логируем успешный вызов в БД
        # log_request(endpoint="summarize", status="completed")
        return {"summary": summary}

    except Exception as e:
        # log_request(endpoint="summarize", status="error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/keywords")
async def keywords_endpoint(request: TextRequest):
    """
    Эндпоинт для получения ключевых слов из отзывов.

    Входные данные:
      - text: строка, содержащая отзывы (каждый отзыв — с новой строки)

    Логика:
      1. Разбивает входной текст на список отзывов.
      2. Загружает стоп-слова.
      3. Для каждого отзыва получает лемматизированный вариант.
      4. Вызывает функцию kw_counter для подсчёта самых частотных слов.
      5. Логируется успешный вызов или ошибка в БД.
    """
    if not request.text:
        raise HTTPException(status_code=400, detail="Параметр 'text' не может быть пустым.")

    try:
        reviews = split_reviews(request.text)
        stop_words = load_stop_words()

        # получаем лемматизированную версию каждого отзыва
        lemmas = [text_preproc(review, stop_words=stop_words) for review in reviews]

        keywords = kw_counter(lemmas)

        # логируем успешный вызов в БД
        # log_request(endpoint="keywords", status="completed")
        return {"keywords": keywords}

    except Exception as e:
        # log_request(endpoint="keywords", status="error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/inference")
async def inference_endpoint(request: TextRequest):
    """
    Эндпоинт для асинхронного запуска инференса (обработки отзывов) с использованием Celery.
    
    Логика:
      1. Проверяется, что параметр text не пустой.
      2. Задача на обработку текста ставится в очередь через Celery.
      3. Сохраняется информация о постановке задачи (например, статус "queued") в базу данных.
      4. Клиенту возвращается идентификатор задачи (task_id) для дальнейшего отслеживания статуса.
    """
    if not request.text:
        raise HTTPException(status_code=400, detail="Параметр 'text' не может быть пустым.")

    try:
        task = run_model_inference.delay(request.text)
        # log_request(endpoint="inference", status="queued", task_id=task.id)
        return {"task_id": task.id, "status": "queued"}
    except Exception as e:
        # log_request(endpoint="inference", status="error")
        raise HTTPException(status_code=500, detail=str(e))
