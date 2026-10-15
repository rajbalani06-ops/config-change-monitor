FROM python:3.12.7-slim-bookworm

RUN useradd --create-home --uid 10001 ccm \
    && mkdir -p /app /watched \
    && chown -R ccm:ccm /app /watched

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src /app/src
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1
USER ccm
EXPOSE 9100
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/')" || exit 1
CMD ["python", "-m", "ccm.main"]
