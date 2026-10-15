FROM python:3.12.7-slim-bookworm
WORKDIR /app
COPY server.py /app/server.py
USER nobody
EXPOSE 8088
CMD ["python", "server.py"]
