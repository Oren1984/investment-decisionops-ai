#!/bin/sh
# Creates the owner database and the physically separate demo database with their own roles.
# The demo roles have no access to the owner database (CONNECT revoked from PUBLIC).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v app_pw="$APP_DB_PASSWORD" -v demo_owner_pw="$DEMO_OWNER_PASSWORD" -v demo_ro_pw="$DEMO_RO_PASSWORD" <<'EOSQL'
CREATE ROLE decisionops LOGIN PASSWORD :'app_pw';
CREATE DATABASE decisionops OWNER decisionops;
REVOKE ALL ON DATABASE decisionops FROM PUBLIC;

CREATE ROLE demo_owner LOGIN PASSWORD :'demo_owner_pw';
CREATE ROLE demo_ro LOGIN PASSWORD :'demo_ro_pw';
CREATE DATABASE decisionops_demo OWNER demo_owner;
REVOKE ALL ON DATABASE decisionops_demo FROM PUBLIC;
GRANT CONNECT ON DATABASE decisionops_demo TO demo_ro;

\connect decisionops
CREATE EXTENSION IF NOT EXISTS vector;

\connect decisionops_demo
CREATE EXTENSION IF NOT EXISTS vector;
GRANT USAGE ON SCHEMA public TO demo_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE demo_owner IN SCHEMA public GRANT SELECT ON TABLES TO demo_ro;
EOSQL
