# Enemy microservice dockerfile
# Use official Python image
FROM python:3.12

# Set working directory inside the container
WORKDIR /app

# Copy requirements and install dependencies
COPY ./requirements.txt /app/
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy necessary files
COPY app.py /app/

# Expose Flask port
EXPOSE 5005

# Start the enemy service
CMD ["python", "/app/app.py"]
