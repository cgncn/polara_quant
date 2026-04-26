FROM eclipse-temurin:17-jre

RUN apt-get update && apt-get install -y --no-install-recommends unzip curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# User must place clientportal.gw.zip here before building.
# Download from: https://www.interactivebrokers.com/en/trading/ib-api.php#cpapi1
COPY clientportal.gw.zip .
RUN unzip -q clientportal.gw.zip && mv clientportal/* . && rm -rf clientportal clientportal.gw.zip

COPY conf.yaml root/conf.yaml

EXPOSE 5000

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
  CMD curl -sk https://localhost:5000/v1/api/iserver/auth/status | grep -q '"connected"' || exit 1

CMD ["bin/run.sh", "root/conf.yaml"]
