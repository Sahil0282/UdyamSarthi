FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# pyogrio and shapely ship manylinux wheels with GDAL/GEOS/PROJ bundled, so no
# system geo libraries are needed. curl is only here for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY core/ core/
COPY api/ api/
COPY web/ web/
COPY cli.py .
COPY data/rules/ data/rules/
COPY data/sectors/ data/sectors/
COPY data/derived/plp_index/ data/derived/plp_index/

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
