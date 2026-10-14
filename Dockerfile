# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Metadatas
LABEL maintainer="BCHEF Bourges Automation <bourges@bchef.fr>"
LABEL description="Plateforme autonome de publication quotidienne pour BCHEF Bourges"

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Paris

# Configure Timezone & Install base system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ffmpeg \
    fonts-liberation \
    curl \
    wget \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and its Linux OS dependencies
RUN playwright install --with-deps chromium

# Copy application source code and assets
COPY src/ /app/src/
COPY assets/ /app/assets/

# Create runtime directories
RUN mkdir -p /app/uploads/stories /app/uploads/videos /app/processed/stories /app/processed/videos /app/processed/archive /app/data

# Expose web dashboard port
EXPOSE 8000

# Healthcheck to verify the web server and scheduler are responding
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/status || exit 1

# Default command: Launch web server + background scheduler
CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
