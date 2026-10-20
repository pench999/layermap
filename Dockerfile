FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY generate_diagram.py network_model.py view_model.py bench_scale.py input_support.py merge_model.py vpn_model.py source_map.py redundancy.py web_app.py test_*.py lan-sample.yaml ./
COPY samples/ ./samples/
COPY --from=frontend /frontend/dist ./frontend/dist
USER 1000:1000
EXPOSE 8000
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
