# BdREN VAULT - container image.
# Runs on any Linux server, VM or cloud host that has Docker. Data lives in the /data volume.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DBMS_DATA=/data \
    HOST=0.0.0.0 \
    PORT=8000

# ping is used for device reachability checks; ssh client libraries are installed via pip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 dbms \
 && mkdir -p /data && chown -R dbms:dbms /data /app
USER dbms

VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "manage.py", "serve", "--host", "0.0.0.0", "--port", "8000"]
