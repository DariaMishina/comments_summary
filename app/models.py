import json
import re
import requests
from collections import Counter
import logging
import torch
import pandas as pd
import numpy as np
from pymystem3 import Mystem
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer
import gensim.corpora as corpora
from gensim.models.coherencemodel import CoherenceModel
from cuml.manifold import UMAP as GPU_UMAP
from cuml.cluster import HDBSCAN as GPU_HDBSCAN
from sentence_transformers import SentenceTransformer
from expiringdict import ExpiringDict
import nltk
nltk.download("stopwords")

mystem = Mystem()
vectorizer_model = CountVectorizer()
embedding_cache = ExpiringDict(max_age_seconds=604800, max_len=100)
embedding_model = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    device="cuda"
)

def get_summary_vllm(texts):
    logging.info('get_summary_vllm')
    if torch.cuda.is_available():
        text = '\n\n'.join(texts)
        if len(texts) < 4:
            output = re.sub('\n[\n\ ]*', '\n', text)
        else:
            req_data = {
                "model": "Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it",
                "max_tokens": 256,
                "temperature": 0.1,
                "top_p": 0.98,
                "repetition_penalty": 1.05,
                "stop": ["</s>"],
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты получишь тексты отзывов покупателей об одном продукте. "
                                "Выдели кратко не больше 5 основных моментов, которые отмечают покупатели."
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ]
            }
            response = requests.post('http://vllm:8000/v1/chat/completions', json=req_data)
            logging.info(response)
            if response.status_code != 200:
                raise Exception
            output = json.loads(response.text)['choices'][0]['message']['content']
        return output
    else:
        return "нет GPU - нет и саммари"

def get_attr_vllm(texts):
    logging.info('get_attr_vllm')
    if torch.cuda.is_available():
        text = '\n\n'.join(texts)

        SYSTEM_PROMPT = (
            "You are an assistant that analyzes Russian customer reviews of a single product. "
            "Extract every product *attribute* that is mentioned (e.g., «вкус», «запах», «текстура», «цвет»). "
            "An attribute must be 1‑3 short Russian words, concise and clear. "
            "For each attribute, list every *characteristic* reviewers use to describe it "
            "(e.g., «сладкий», «свежий», «мягкий», «сочный»). "
            "If reviewers say the product is «кислый», «сладкий» or «горький», the attribute is «вкус». "
            "If they say the product is «с комочками» or «волокнистый», the attribute is «консистенция». "
            "Extract **all** attributes that appear in the reviews. "
            "Return **ONLY ONE** JSON array and nothing else — no markdown, no comments. "
            "Each element must have the keys \"attribute\" and \"characteristic\" (both in Russian). "
            "Example:\n"
            "[{\"attribute\":\"вкус\",\"characteristic\":\"сладкий\"}, "
            "{\"attribute\":\"консистенция\",\"characteristic\":\"волокнистая\"}]"
        )

        req_data = {
            "model": "Vikhrmodels/Vikhr-YandexGPT-5-Lite-8B-it",
            "max_tokens": 400,
            "temperature": 0.2,
            "top_k": 1,
            "stop": ["</s>"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT,},
                {"role": "user", "content": text}
            ]
        }
        try:
            response = requests.post('http://vllm:8000/v1/chat/completions', json=req_data)
            logging.info(f"Response code: {response.status_code}")
            if response.status_code != 200:
                logging.error(f"Error: {response.text}")
                raise Exception
            output = json.loads(response.text)['choices'][0]['message']['content']
            output = process_attr(output)
        except Exception as e:
            logging.error(f"Failed to get attributes: {e}")
            output = ""
        return output
    else:
        return "нет GPU - нет и атрибутов"

def grab_json(text: str):
    """
    Возвращает список словарей из ответа модели.
    1.  Сначала пытается найти нормальный [ … ] массив.
    2.  Если не нашёл, ищет последовательность {...}{...}{...}
        (с запятой или без) и парсит каждую скобку отдельно.
    3.  Убирает дубликаты.
    """
    # Пробуем массив [...]
    m = re.search(r"\[[\s\S]*?]", text)
    if m:
        return json.loads(m.group(0))

    # Последовательность {} {} {} без скобок массива
    pods = re.findall(r"\{[^{}]+\}", text)
    if not pods:
        raise ValueError("no JSON objects")
    objs = [json.loads(p) for p in pods]

    # Дедупликация (одинаковые пары attribute+characteristic)
    seen, uniq = set(), []
    for d in objs:
        key = (d.get("attribute"), d.get("characteristic"))
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq

def process_attr(text):
    try:
        res = ''
        arr = grab_json(text)
        groups = pd.DataFrame(arr).groupby('attribute')
        for gr in groups:
            res += f"{gr[0]}: {'; '.join(gr[1]['characteristic'])};\n"
    except Exception:
        res = text
    return res.strip()


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
    try:
        text = ''.join(mystem.lemmatize(text))
        # text = text
        tokens = re.findall(token_pattern, text)
        tokens = [t.replace(' ', '_') for t in tokens
                if t.split()[-1] not in stop_words]
        text = ' '.join(tokens)
        return text
    except:
        return text

def get_representative_texts(lemmatized, originals, mode='strict'):
    """
    извлекает представительные тексты из оригинальных документов на основе их лемматизированных версий
    и тематического моделирования с использованием BERTopic

    если количество лемматизированных текстов меньше или равно 30, возвращаются все оригинальные тексты
    В противном случае:
    - выбирается оптимальная модель BERTopic на основе максимального значения когерентности
    - извлекаются тексты, присутствующие в представительных документах каждого топика

    args:
        lemmatized (list of str): список лемматизированных текстов
        originals (list of str): список оригинальных текстов
        mode (str) 'strict': по 1 документу на каждую тему (ближайший к центроиду)
        'expanded': все документы из BERTopic -> Representative_Docs.
    returns:
        list of str: список репрезентативных оригинальных отзывов
    """
    logging.info("get_representative_texts")

    if isinstance(lemmatized, pd.Series):
        lemmatized = lemmatized.reset_index(drop=True)
    if isinstance(originals, pd.Series):
        originals = originals.reset_index(drop=True)

    if len(lemmatized) <= 30:
        return list(originals)

    try:
        joined_text = "\n".join(lemmatized)
        hash_key = hash(joined_text)
        if hash_key in embedding_cache:
            embeddings = embedding_cache[hash_key]
        else:
            embeddings = embedding_model.encode(
                lemmatized, show_progress_bar=False, batch_size=64
            )
            embedding_cache[hash_key] = embeddings

        analyzer = vectorizer_model.build_analyzer()
        tokens = [analyzer(doc) for doc in lemmatized]
        dictionary = corpora.Dictionary(tokens)
        corpus = [dictionary.doc2bow(t) for t in tokens]

        topic_models, coherence_values = compute_bertopic_coherence_values(
            lemmatized, embeddings, dictionary, tokens, corpus,
            limit=5, start=2, step=1
        )

        if not coherence_values:
            return list(originals)

        max_index = coherence_values.index(max(coherence_values))
        optimal_model = topic_models[max_index]
        document_info = optimal_model.get_document_info(lemmatized)
        topics = document_info["Topic"].to_numpy()

        res = []

        if mode == 'strict':
            # строгий режим: по 1 документу на тему
            for topic_id in np.unique(topics):
                if topic_id == -1:
                    continue
                doc_indices = np.where(topics == topic_id)[0]
                if len(doc_indices) == 0:
                    continue
                cluster_embeddings = embeddings[doc_indices]
                centroid = cluster_embeddings.mean(axis=0)
                dists = np.linalg.norm(cluster_embeddings - centroid, axis=1)
                best_doc_idx = doc_indices[np.argmin(dists)]
                if isinstance(originals, pd.Series):
                    res.append(originals.iloc[best_doc_idx])
                else:
                    res.append(originals[best_doc_idx])

        elif mode == 'expanded':
            # расширенный режим: Representative_Docs от BERTopic
            rep_docs_dict = {}
            topic_info = optimal_model.get_topic_info()
            for _, row in topic_info.iterrows():
                if row["Topic"] == -1:
                    continue
                for d in row["Representative_Docs"]:
                    rep_docs_dict[d] = row['Topic']

            # сопоставляем лемматизированные с оригинальными
            result_df = pd.DataFrame({'lemmas': lemmatized, 'original': originals})
            result_df['topic_num'] = result_df['lemmas'].map(rep_docs_dict)
            res = result_df.groupby('topic_num')['original'].head(3).to_list()

        else:
            raise ValueError("mode должен быть 'strict' или 'expanded'")

        return res

    except Exception as err:
        logging.warning("Couldn't get topics")
        logging.exception(err)
        return list(originals)[:30]


def compute_bertopic_coherence_values(docs, embeddings, dictionary, tokens, corpus, limit, start=2, step=1):
    """
    вычисляет значения когерентности для моделей BERTopic, обученных с различными размерами минимального топика

    для каждого значения минимального размера топика:
    - создается и обучается модель BERTopic
    - выполняется предобработка документов
    - строится словарь и корпус для оценки когерентности
    - вычисляется когерентность для топиков модели

    args:
        docs (list of str): список документов для тематического моделирования
        embeddings
        dictionary
        tokens
        corpus 
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
        # на GPU модели
        umap_model = GPU_UMAP(n_components=5, n_neighbors=15, min_dist=0.0, metric="cosine")
        hdbscan_model = GPU_HDBSCAN(min_cluster_size=size)

        topic_model = BERTopic(
            min_topic_size=size,
            language="russian",
            calculate_probabilities=False,
            nr_topics=10,
            vectorizer_model=vectorizer_model,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model
        )

        topics, _ = topic_model.fit_transform(docs, embeddings)

        model_topics = {
            topic: words for topic, words in topic_model.get_topics().items()
            if words and topic != -1
        }

        topic_words = [
            [word for word, _ in model_topics[topic]]
            for topic in model_topics
        ]

        if not topic_words:
            continue  # пропускаем модель без тем

        coherence_model = CoherenceModel(
            topics=topic_words,
            texts=tokens,
            corpus=corpus,
            dictionary=dictionary,
            coherence="c_v",
            processes=4
        )
        coherence_values.append(coherence_model.get_coherence())
        topic_models.append(topic_model)

    return topic_models, coherence_values


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

def load_stop_words():
    """
    Загружает список стоп-слов из CSV и nltk.
    Если CSV не найден, используется только nltk.
    """
    try:
        stop_words_csv = pd.read_csv('stop_words.csv')['word'].to_list()
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