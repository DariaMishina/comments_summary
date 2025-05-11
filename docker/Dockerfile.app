FROM rapidsai/base:25.04-cuda11.8-py3.11

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


COPY . /app
WORKDIR /app


ENV PYTHONPATH="/app"


EXPOSE 8000


CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "app.main:app"]