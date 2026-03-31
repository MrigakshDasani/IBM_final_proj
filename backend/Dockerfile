FROM python:3.10-slim

# Install system dependencies for OpenCV and ML libraries
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libxcb1 \
    libx11-6 \
    libxext6 \
    libsm6 \
    libice6 \
    libxrender1 \
    libfontconfig1 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Railway uses the $PORT variable for binding
ENV PORT=8080

# Command to run the application
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
