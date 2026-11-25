# Python 3.11 hafif tabanlı imaj
FROM python:3.11-slim

# Python tamponlamasını kapat ve bytecode üretimini engelle
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=80

WORKDIR /app

# Bağımlılık dosyasını kopyala ve önbelleksiz yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kaynak kodlarını kopyala
COPY . .

# ACI için 80 portunu dışa aç
EXPOSE 80

# Üretim ortamı için Gunicorn WSGI sunucusu ile 80 portunda başlat
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
