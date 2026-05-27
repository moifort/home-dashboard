FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > .version

RUN mkdir -p /data

VOLUME /data
EXPOSE 5000

CMD ["python", "server.py"]
