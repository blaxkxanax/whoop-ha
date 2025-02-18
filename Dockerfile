FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 2008

CMD ["gunicorn", "--bind", "0.0.0.0:2008", "app:app"] 