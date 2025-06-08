# Dockerfile

# --- Base Image ---
# Start from an official, lightweight Python image.
# Using a specific version is good practice for reproducibility.
FROM python:3.11-slim

# --- Environment Variables ---
# Set environment variables for the container.
# Tells Python not to buffer stdout/stderr, making logs appear immediately.
ENV PYTHONUNBUFFERED 1
# Sets the working directory inside the container.
ENV APP_HOME /app
WORKDIR $APP_HOME

# --- Install Dependencies ---
# Copy only the requirements file first. This leverages Docker's layer caching.
# If requirements.txt doesn't change, Docker won't re-run this layer, speeding up future builds.
COPY requirements.txt .

# Install the Python dependencies from requirements.txt.
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy Application Code ---
# Copy the 'src' directory from your local machine into the container's working directory.
# The first '.' means the 'src' folder itself.
COPY ./src ./src

# Copy the configuration file.
COPY config.yaml .

# --- Expose Port ---
# Inform Docker that the container listens on port 5000 at runtime.
# This is for documentation; the actual port mapping is done in docker-compose.
EXPOSE 5000

# --- Run Command ---
# The command to run when the container starts.
# We use the '-m' flag to run the server as a module, which is robust for imports.
CMD ["python", "-m", "src.webhook_server.server"]