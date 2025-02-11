from celery import Celery
import nltk


from app.models import get_summary, kw_counter, text_preproc, get_representative_texts
from app.database import update_task_status
from app.config import CELERY_BROKER_URL

# инициализируем сelery с использованием rabbitmq TODO заменить подключение 
# TODO - сейчас просто такая же логика как в обычных эндпоинтах только в одном месте
#  (саммари + ключевые, надо придумать что-то еще для очереди)
celery_app = Celery('tasks', broker=CELERY_BROKER_URL)


nltk.download('stopwords', quiet=True)
from nltk.corpus import stopwords

def split_reviews(text: str):
    """
    Разбивает входной текст на отдельные отзывы по переводу строки.
    Если отзывы не выделены — выбрасывается исключение.
    """
    reviews = [line.strip() for line in text.splitlines() if line.strip()]
    if not reviews:
        raise ValueError("Не удалось выделить ни одного отзыва из входного текста")
    return reviews

@celery_app.task
def run_model_inference(text: str):
    """
    Асинхронная задача для инференса:
      1. Разбивает входной текст на отзывы.
      2. Для каждого отзыва выполняет лемматизацию через функцию text_preproc.
      3. Пытается выделить репрезентативные отзывы (get_representative_texts),
         при ошибке берет первые 15 отзывов.
      4. Вызывает get_summary для получения краткого описания.
      5. Вычисляет ключевые слова с помощью kw_counter.
      6. Обновляет статус задачи в базе данных (от "started" до "completed" или "error").
    """
    task_id = run_model_inference.request.id
    update_task_status(task_id=task_id, status="started")
    try:
        reviews = split_reviews(text)
        stop_words = set(stopwords.words("russian"))
        
        # получаем лемматизированную версию каждого отзыва
        lemmas = [text_preproc(review, stop_words=stop_words) for review in reviews]
        
        try:
            rep_reviews = get_representative_texts(lemmas, reviews)
        except Exception:
            rep_reviews = reviews[:15]
        
        # получаем суммарное описание с использованием LLM (функция get_summary из models.py)
        summary = get_summary(rep_reviews)
        # вычисляем наиболее частотные ключевые слова
        keywords = kw_counter(lemmas)
        
        result = {"summary": summary, "keywords": keywords}
        update_task_status(task_id=task_id, status="completed")
        return result

    except Exception as e:
        update_task_status(task_id=task_id, status="error")
        raise e
