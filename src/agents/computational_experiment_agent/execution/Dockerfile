FROM python:3.12.12-slim
RUN python -m pip install --no-cache-dir numpy==2.3.5 scipy==1.16.3 pyscf==2.11.0 jsonschema==4.25.1 sympy==1.14.0
RUN python -m pip freeze --all > /opt/environment.lock
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /project
