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
# No socket dial here: the seccomp profile denies connect(), so the probe
# checks the listening port via /proc and runs one sandbox job instead.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -m code_runner.healthcheck
ENTRYPOINT ["python", "-m", "code_runner"]
