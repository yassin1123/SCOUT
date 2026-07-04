# Optional container image (spec calls it a nice-to-have; cron-on-VPS is the
# primary deployment). Runs one mode per invocation:
#
#   docker build -t scout .
#   docker run --rm --env-file .env \
#     -v scout-data:/opt/scout/data -v scout-logs:/opt/scout/logs \
#     scout morning
#
# Schedule with host cron the same way as the bare-metal install.

FROM python:3.11-slim

ENV TZ=Europe/London \
    PYTHONUNBUFFERED=1

WORKDIR /opt/scout

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "scout.py"]
CMD ["morning"]
