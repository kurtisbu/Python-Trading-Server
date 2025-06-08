# Dockerfile (Multi-Stage)

# --- Stage 1: The "base" image with all dependencies ---
# We give this stage a name: 'base'
FROM python:3.11-slim AS base

# Set common environment variables
ENV PYTHONUNBUFFERED 1
ENV APP_HOME /app
WORKDIR $APP_HOME

# Install all dependencies from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# --- Stage 2: The "backend" service image ---
# This stage starts from our 'base' image, so it already has all dependencies
FROM base AS backend

# Copy only the files needed for the backend
WORKDIR $APP_HOME
COPY ./src ./src
COPY config.yaml .

# Expose the backend's port
EXPOSE 5000

# The command to run the backend server
CMD ["python", "-m", "src.webhook_server.server"]


# --- Stage 3: The "frontend" dashboard image ---
# This stage ALSO starts from our 'base' image
FROM base AS frontend

# Copy only the file needed for the frontend
WORKDIR $APP_HOME
COPY dashboard.py .

# Expose the dashboard's default port
EXPOSE 8501

# The command to run the Streamlit dashboard
CMD ["streamlit", "run", "dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]