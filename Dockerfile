FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG GIT_COMMIT=unknown
RUN echo "${GIT_COMMIT:0:7}" > .version

RUN mkdir -p /data

VOLUME /data
EXPOSE 5000

CMD ["python", "server.py"]
