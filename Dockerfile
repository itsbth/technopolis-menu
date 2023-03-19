FROM python:3.9 AS python
ENV PYTHONUNBUFFERED=true
WORKDIR /app

FROM python AS poetry
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PATH="$POETRY_HOME/bin:$PATH"
RUN curl -sSL https://install.python-poetry.org | python3 -
COPY . ./
RUN poetry install --no-interaction --no-ansi -vvv

FROM python AS runtime
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=poetry /app /app
CMD ["python", "main.py"]