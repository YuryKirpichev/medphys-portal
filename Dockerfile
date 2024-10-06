FROM python:3.12-slim
WORKDIR /usr/src/app


COPY ./app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8055/tcp

CMD ["python", "./app.py"]
