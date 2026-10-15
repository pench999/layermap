FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY generate_diagram.py test_generate_diagram.py lan-sample.yaml ./
USER 1000:1000
CMD ["python", "-m", "unittest", "-v", "test_generate_diagram.py"]
