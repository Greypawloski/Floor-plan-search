FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install app dependencies
# (playwright itself is already in the base image at the correct version)
COPY requirements.txt .
RUN pip install --no-cache-dir schedule python-dotenv && \
    pip install --no-cache-dir playwright-stealth || true

COPY . .

CMD ["python", "monitor.py"]
