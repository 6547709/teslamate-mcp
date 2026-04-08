FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

COPY tesla.py ./

EXPOSE 8080

CMD ["python", "tesla.py"]
