from celery import Celery

from app.models import text_preproc, get_representative_texts, get_summary_vllm, load_stop_words, split_reviews
from app.database import update_task_status
from app.config import CELERY_BROKER_URL

celery_app = Celery('tasks', broker=CELERY_BROKER_URL)


# @celery_app.task
@celery_app.task(queue='huge_summarize_queue')
def run_model_in_queue(text: str):
    """
    Асинхронная задача для инференса если отзывов ОЧЕНЬ много и надо подождать пока ЛЛМ их пережует:
      1. Разбивает входной текст на список отзывов.
      2. Загружает стоп-слова.
      3. Для каждого отзыва получает лемматизированный вариант с помощью text_preproc.
      4. Пытается вычислить репрезентативные отзывы с помощью get_representative_texts.
         Если возникает ошибка, берутся первые 5 отзывов.
      5. Вызывается функция get_summary для получения саммари.
      6. Обновляет статус задачи в базе данных (от "started" до "completed" или "error").
    """
    task_id = run_model_in_queue.request.id
    update_task_status(task_id=task_id, status="started")
    try:
        reviews = split_reviews(text)
        stop_words = load_stop_words()
        
        # получаем лемматизированную версию каждого отзыва
        lemmas = [text_preproc(review, stop_words=stop_words) for review in reviews]
        
        try:
            rep_reviews = get_representative_texts(lemmas, reviews)
        except Exception:
            rep_reviews = reviews[:15]
        
        # получаем суммарное описание с использованием LLM (функция get_summary из models.py)
        summary = get_summary_vllm(rep_reviews)
        
        result = {"summary": summary}
        update_task_status(task_id=task_id, status="completed")
        return result

    except Exception as e:
        update_task_status(task_id=task_id, status="error")
        raise e
