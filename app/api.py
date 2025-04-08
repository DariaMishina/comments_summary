from fastapi import APIRouter, HTTPException
from datetime import datetime
import pandas as pd
from pydantic import BaseModel

from app.models import text_preproc, get_representative_texts, get_summary, kw_counter, load_stop_words, split_reviews
from app.tasks import run_model_in_queue
# from app.database import log_request, get_task_status 

router = APIRouter()

class TextRequest(BaseModel):
    text: str

@router.get("/ping")
async def ping():
    # log_request(endpoint="ping", status="completed")
    return {"ping": "Привет! Я микросервис и я живой."}

@router.post("/summarize")
async def summarize_endpoint(request: TextRequest):
    """
    Эндпоинт для получения краткого саммари отзывов.

    Входные данные:
      - text: строка, содержащая отзывы (каждый отзыв — с новой строки)

    Логика:
      1. Разбивает входной текст на список отзывов.
      2. Загружает стоп-слова.
      3. Для каждого отзыва получает лемматизированный вариант с помощью text_preproc.
      4. Пытается вычислить репрезентативные отзывы с помощью get_representative_texts.
         Если возникает ошибка, берутся первые 5 отзывов.
      5. Вызывается функция get_summary для получения саммари.
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


@router.post("/huge_summarize")
async def huge_summarize(request: TextRequest):
    """
    Отправляет задачу в очередь RabbitMQ.
    """
    task = run_model_in_queue.apply_async(args=[request.text], queue='huge_summarize_queue')
    # log_request(endpoint="huge_summarize", status="submitted", task_id=task.id)
    return {"task_id": task.id, "status": "submitted"}

@router.get("/task_status/{task_id}")
async def get_task_status_endpoint(task_id: str):
    """
    Получение статуса задачи по task_id.
    """
    status = get_task_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "status": status}