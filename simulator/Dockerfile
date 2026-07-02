FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx python-dotenv

COPY . .

# BACKEND_URL передається через compose (http://backend:8000)
CMD ["python", "-u", "main.py"]
