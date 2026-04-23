FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create necessary dirs
RUN mkdir -p reports/charts data logs

# Expose web port
EXPOSE 5000

# Default: run web dashboard
CMD ["python", "web_dashboard.py"]
