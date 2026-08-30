# Foundryx Code runner - a separately deployed, stdlib-only sandbox host for
# the ``code.run`` workflow action. Ships ONLY this package: no application
# code, no pip packages, no secrets. Run read-only, non-root, on an
# internal-only network (see docker-compose.yml `code_runner`).
FROM python:3.12-slim

RUN useradd -r -u 10001 -s /usr/sbin/nologin runner
WORKDIR /runner
COPY . /runner/code_runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER runner
EXPOSE 8011
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8011/health', timeout=3).status==200 else 1)"
ENTRYPOINT ["python", "-m", "code_runner"]
