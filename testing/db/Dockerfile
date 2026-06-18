# MariaDB for the test stack, mirroring the production kegberry/db image.
# The timezone tables must be populated or Django's CONVERT_TZ() raises
# "Database returned an invalid datetime value" on date-range queries
# (e.g. /sessions/). Kept self-contained in this repo so CI does not need
# the external kegberry deployment repo checked out.
FROM mariadb:10.11

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY init_tzdata.sh /docker-entrypoint-initdb.d/init_tzdata.sh
RUN chmod +x /docker-entrypoint-initdb.d/init_tzdata.sh
