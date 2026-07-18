FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    shared-mime-info \
    cron \
    # Playwright / Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (headless shell — no X11 needed)
RUN python -m playwright install --with-deps chromium

COPY . .
RUN mkdir -p output logs && chmod +x /app/entrypoint.sh

ENV CONFIG_PATH=/app/instance/config.json
# Disable the Playwright browser-download prompt at runtime
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENTRYPOINT ["/app/entrypoint.sh"]
