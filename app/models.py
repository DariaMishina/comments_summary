import re
from collections import Counter

import torch
import pandas as pd
from pymystem3 import Mystem
from bertopic import BERTopic
import gensim.corpora as corpora
from gensim.models.coherencemodel import CoherenceModel
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

mystem = Mystem()


class LLM:
    """
    Класс для работы с большой языковой моделью (LLM)

    Атрибуты:
        config (dict): конфиг для генерации текста
        prompt (str): шаблон системного сообщения для языковой модели
        model: загруженная предобученная языковая модель
        tokenizer: токенизатор для языковой модели
        pipe: pipeline для генерации текста
    """
    config = dict(
        max_new_tokens=512,
        do_sample=True,
        num_beams=1,
        temperature=0.25,
        top_k=50,
        top_p=0.98,
        eos_token_id=79097,
    )
    prompt = "Ты получишь тексты отзывов покупателей об одном продукте. " \
                            "Выдели кратко не больше 5 основных моментов, которые отмечают покупатели."

    def __init__(self):
        """
        инициализирует экземпляр LLM, загружая предобученную языковую модель, токенизатор
        и настраивая pipeline для генерации текста
        """
        print('Cuda: ', torch.cuda.is_available())
        print('model')
        self.model = AutoModelForCausalLM.from_pretrained(
            "Vikhrmodels/Vikhr-7B-instruct_0.4",
            device_map="auto",
            # attn_implementation="flash_attention_2",
            torch_dtype=torch.bfloat16,
        )
        print('tokenizer')
        self.tokenizer = AutoTokenizer.from_pretrained("Vikhrmodels/Vikhr-7B-instruct_0.4")
        print('pipe')
        self.pipe = pipeline("text-generation", model=self.model, tokenizer=self.tokenizer)

def get_summary(texts):
    """
    генерирует сводку отзывов, используя либо простую обработку текста, либо языковую модель

    если количество текстов меньше 4, выполняется предварительная обработка текста
    в противном случае используется LLM для генерации сводки

    args:
        texts (list of str): список текстов отзывов

    returns:
        str: сгенерированная сводка или обработанный текст
    """
    print('get_summary')
    if torch.cuda.is_available():
        text = '\n\n'.join(texts)
        if len(texts) < 4:
            output = re.sub('\n[\n\ ]*', '\n', text)
        else:
            llm = LLM()
            print('Model loaded')
            prompt = llm.tokenizer.apply_chat_template([{
                "role": "system",
                "content": llm.prompt
            }, {
                "role": "user",
                "content": text
            }], tokenize=False, add_generation_prompt=True)
            output = llm.pipe(prompt, **llm.config)
            output = output[0]['generated_text'][len(prompt):].strip()
        return output
    else:
        return "нет GPU - нет и саммари"


def text_preproc(text: str, token_pattern: str = r'(?:не\ |ни\ |нет\ |\b)[Ё-ё]{4,}', stop_words=None) -> str:
    """
    выполняет предобработку текста:
    - лемматизация с использованием Mystem
    - поиск токенов по заданному регулярному выражению
    - замена пробелов в найденных токенах на символы подчеркивания
    - исключение токенов, оканчивающихся на стоп-слова

    args:
        text (str): исходный текст для обработки
        token_pattern (str, optional): регулярное выражение для поиска токенов. по умолчанию
            r'(?:не\ |ни\ |нет\ |\b)[Ё-ё]{4,}'.
        stop_words (set, optional): множество стоп-слов для фильтрации токенов

    returns:
        str: обработанный текст, состоящий из отобранных токенов
    """
    if not stop_words:
        stop_words = set()
    text = ''.join(mystem.lemmatize(text))
    tokens = re.findall(token_pattern, text)
    tokens = [t.replace(' ', '_') for t in tokens
              if t.split()[-1] not in stop_words]
    text = ' '.join(tokens)
    return text

def compute_bertopic_coherence_values(docs, limit, start=2, step=3):
    """
    вычисляет значения когерентности для моделей BERTopic, обученных с различными размерами минимального топика

    для каждого значения минимального размера топика:
    - создается и обучается модель BERTopic
    - выполняется предобработка документов
    - строится словарь и корпус для оценки когерентности
    - вычисляется когерентность для топиков модели

    args:
        docs (list of str): список документов для тематического моделирования
        limit (int): верхняя граница для изменения минимального размера топика
        start (int, optional): начальное значение минимального размера топика. По умолчанию 2
        step (int, optional): шаг изменения минимального размера топика. По умолчанию 3

    returns:
        tuple:
            - topic_models (list): список обученных моделей BERTopic
            - coherence_values (list): список значений когерентности, соответствующих моделям
    """
    coherence_values = []
    topic_models = []
    for size in range(start, limit, step):
        topic_model = BERTopic(
            min_topic_size=size,
            language="russian",
            # n_gram_range=(2, 3)
        )
        topics, _ = topic_model.fit_transform(docs)

        cleaned_docs = topic_model._preprocess_text(docs)
        vectorizer = topic_model.vectorizer_model
        analyzer = vectorizer.build_analyzer()
        tokens = [analyzer(doc) for doc in cleaned_docs]

        dictionary = corpora.Dictionary(tokens)
        corpus = [dictionary.doc2bow(token) for token in tokens]

        topics = topic_model.get_topics()
        topics.pop(-1, None)
        topic_words = [
            [word for word, _ in topic_model.get_topic(topic)] for topic in topics
        ]
        if not topic_words:
            continue

        coherence_model = CoherenceModel(
            topics=topic_words,
            texts=tokens,
            corpus=corpus,
            dictionary=dictionary,
            coherence="c_v",
        )
        coherence_values.append(coherence_model.get_coherence())
        topic_models.append(topic_model)

    return topic_models, coherence_values


def get_representative_texts(lemmatized, originals):
    """
    извлекает представительные тексты из оригинальных документов на основе их лемматизированных версий
    и тематического моделирования с использованием BERTopic

    если количество лемматизированных текстов меньше или равно 10, возвращаются все оригинальные тексты
    В противном случае:
    - выбирается оптимальная модель BERTopic на основе максимального значения когерентности
    - извлекаются тексты, присутствующие в представительных документах каждого топика

    args:
        lemmatized (list of str): список лемматизированных текстов
        originals (list of str): список оригинальных текстов

    returns:
        list of str: список представительных оригинальных текстов
    """
    print('get_representative_texts')
    if len(lemmatized) <= 10:
        return originals

    topic_models, coherence_values = compute_bertopic_coherence_values(
        lemmatized, 5, start=2, step=1
    )
    if not len(coherence_values):
        return originals

    max_value = max(coherence_values)
    max_index = coherence_values.index(max_value)
    optimal_model = topic_models[max_index]
    model_topics = optimal_model.get_topic_info()

    res = []

    for lem, orig in zip(lemmatized, originals):
        for topic_index, topic_row in model_topics.iterrows():
            representative_docs = topic_row["Representative_Docs"]
            if lem in representative_docs:
                res.append(orig)

    return res

def kw_counter(texts):
    """
    подсчитывает 10 наиболее часто встречающихся слов в списке текстов

    args:
        texts (list of str): список текстов, в которых необходимо подсчитать слова

    returns:
        list of tuples: список кортежей, где каждый кортеж содержит слово и его частоту, отсортированные по убыванию
    """
    words = ' '.join(texts).split()
    counter = Counter(words)
    return counter.most_common(10)