FROM node:22-bookworm-slim AS trueforge
RUN npm install --prefix /opt/trueforge --omit=dev @truefoundry/trueforge@0.180.0

FROM falkordb/falkordb:6.0.3
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/conferge-venv
COPY --from=trueforge /usr/local/bin/node /usr/local/bin/node
COPY --from=trueforge /opt/trueforge /opt/trueforge
ENV PATH="/opt/conferge-venv/bin:$PATH" PYTHONUNBUFFERED=1 NODE_ENV=production
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt 'mcp==1.30.0' 'python-dotenv>=1,<2'
COPY conferge ./conferge
COPY fixtures ./fixtures
COPY static ./static
COPY data ./data
COPY raw/connection-photos ./raw/connection-photos
COPY scripts/run_demo.py ./scripts/run_demo.py
COPY integrations/trueforge ./integrations/trueforge
EXPOSE 8080
ENTRYPOINT ["bash", "/app/integrations/trueforge/start.sh"]
