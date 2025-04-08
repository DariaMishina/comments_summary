FROM python:3.11

WORKDIR /app

# создала папку wheels в корне проекта, она в гитигноре
COPY requirements.txt ./
COPY wheels /wheels

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --default-timeout=300 --find-links=/wheels -r requirements.txt


COPY . .

EXPOSE 8000

ENV PYTHONPATH="/app"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]