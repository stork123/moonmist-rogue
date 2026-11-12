FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    frotz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY index.html .
COPY MOONMIST.DAT .
COPY moonmist_data.json .

ENV DFROTZ_CMD=dfrotz
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "server.py"]
