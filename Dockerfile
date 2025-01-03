# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set a working directory in the container
WORKDIR /usr/src/app

# Copy the requirements and app code into the container
# (If you have a separate requirements.txt, copy and install that first)
COPY requirements.txt ./requirements.txt

# Install necessary system packages (if needed)
# e.g. libxml2, libxslt for certain functionalities. Adjust as necessary:
RUN apt-get update && apt-get install -y \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
 && pip install -r requirements.txt

# Copy the app code into container
COPY app.py ./app.py

# Expose Streamlit default port
EXPOSE 8501

# Set the command to run Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]