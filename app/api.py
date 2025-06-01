import logging
from fastapi import APIRouter, HTTPException
from datetime import datetime
import pandas as pd
from pydantic import BaseModel

from app.models import text_preproc, get_representative_texts, get_summary_vllm, kw_counter, load_stop_words, split_reviews, get_attr_vllm
from app.tasks import run_model_in_queue
from app.database import log_request, get_task_status 

router = APIRouter()

class TextRequest(BaseModel):
    text: str

@router.get("/ping")
async def ping():
    log_request(endpoint="ping", status="completed")
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
      5. Вызывается функция get_summary_vllm для получения саммари.
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
            rep_reviews = get_representative_texts(lemmas, reviews, mode='expanded')
            logging.info(f"All texts: {len(reviews)}")
            logging.info(f"Repr texts: {len(rep_reviews)}")

        except Exception as err:
            logging.info("Couldn't get topics!!!")
            logging.info(err)
            # если не удалось получить репрезентативные отзывы — берём первые 5 отзывов
            rep_reviews = reviews[:5]

        summary = get_summary_vllm(rep_reviews)
        logging.info(summary)

        # логируем успешный вызов в БД
        log_request(endpoint="summarize", status="completed")
        return {"summary": summary}

    except Exception as e:
        log_request(endpoint="summarize", status="error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/attributes")
async def attributes_endpoint(request: TextRequest):
    """
    Эндпоинт для получения атрибутов и их характеристик из отзывов.

    Входные данные:
      - text: строка, содержащая отзывы (каждый отзыв — с новой строки)

    Логика:
      1. Разбивает входной текст на список отзывов.
      2. Загружает стоп-слова.
      3. Для каждого отзыва получает лемматизированный вариант с помощью text_preproc.
      4. Пытается вычислить репрезентативные отзывы с помощью get_representative_texts.
         Если возникает ошибка, берутся первые 5 отзывов.
      5. Вызывается функция get_attr_vllm для получения атрибутов и их характеристик.
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
            rep_reviews = get_representative_texts(lemmas, reviews, mode='expanded')
            logging.info(f"All texts: {len(reviews)}")
            logging.info(f"Repr texts: {len(rep_reviews)}")
        except Exception as err:
            logging.info("Couldn't get topics!!!")
            logging.info(err)
            # если не удалось получить репрезентативные отзывы — берём первые 5 отзывов
            rep_reviews = reviews[:5]

        attr = get_attr_vllm(rep_reviews)
        logging.info(attr)
        # логируем успешный вызов в БД
        log_request(endpoint="attributes", status="completed")
        return {"attributes": attr}

    except Exception as e:
        log_request(endpoint="attributes", status="error")
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
        logging.info(keywords)
        # логируем успешный вызов в БД
        log_request(endpoint="keywords", status="completed")
        return {"keywords": keywords}

    except Exception as e:
        log_request(endpoint="keywords", status="error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/huge_summarize")
async def huge_summarize(request: TextRequest):
    """
    Отправляет задачу в очередь RabbitMQ.
    """
    task = run_model_in_queue.apply_async(args=[request.text], queue='huge_summarize_queue')
    log_request(endpoint="huge_summarize", status="submitted", task_id=task.id)
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