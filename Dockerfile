FROM python:3.11 AS python
ENV PYTHONUNBUFFERED=true
WORKDIR /app

FROM python AS poetry
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PATH="$POETRY_HOME/bin:$PATH"
RUN curl -sSL https://install.python-poetry.org | python3 -
COPY poetry.lock pyproject.toml ./
# We need no-root as we haven't copied the source code yet
RUN poetry install --no-interaction --no-ansi -vvv --only main --no-root
COPY . ./

FROM python AS runtime
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=poetry /app /app
CMD ["python", "-m", "technopolis_menu"]
