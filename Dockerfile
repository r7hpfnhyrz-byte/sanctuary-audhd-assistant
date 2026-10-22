FROM python:3.12-slim

WORKDIR /app

COPY backend/ ./backend/
COPY start.sh ./start.sh

ENV PORT=8765
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["python3", "-m", "backend.main"]
