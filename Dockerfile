# Use an official Python runtime as a parent image
FROM python:3.10.12

COPY src/ /app
COPY datasets/ /datasets

WORKDIR /app

COPY requirements.txt /app

# Install OpenJDK 11
RUN apt-get update && apt-get install -y openjdk-17-jdk

RUN python -m pip install -U pip

RUN python -m pip install -U setuptools wheel

RUN python -m pip install -r requirements.txt
## Make RUN commands use the new environment
#SHELL ["conda", "run", "-n", "your_environment_name", "/bin/bash", "-c"]
#
## Set environment variables (optional)
#ENV VAR_NAME=var_value
#
## Run the Python script main.py
#CMD ["python", "main.py"]
