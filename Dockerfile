FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV PYDANTIC_AI_NO_BANNER=1
EXPOSE 8000
CMD ["uvicorn", "agentops.api:app", "--host", "0.0.0.0", "--port", "8000"]
