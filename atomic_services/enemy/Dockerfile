# Enemy microservice dockerfile
# Use official Python image
FROM python:3.12

# Set working directory inside the container
WORKDIR /app
# Copy necessary files
COPY . .
# Copy requirements and install dependencies
COPY ./requirements.txt /app/

RUN apt-get update && apt-get install -y netcat-openbsd && apt-get clean && rm -rf /var/lib/apt/lists/*


RUN python -m pip install --no-cache-dir --timeout=120 -i https://pypi.org/simple -r /app/requirements.txt

# Add wait-for-it script permissions
RUN chmod +x /app/wait-for-it.sh

# Expose Flask port
EXPOSE 5005

# Wait for MySQL before starting Flask
CMD ["/app/wait-for-it.sh", "mysql:3306", "--", "python", "-m", "app"]