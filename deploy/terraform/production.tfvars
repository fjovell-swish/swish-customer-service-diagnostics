# Production: reads api-ocpp's PRODUCTION database through a read-only user.
project     = "swishdiag"
environment = "production"
location    = "westeurope"

min_replicas = 1
max_replicas = 2

# custom_domain = "diagnostics.swish.example"
allowed_groups = ["swish-support", "swish-ops"]

# api-ocpp's TENANT_SCHEMAS in production. The read-only connection URL comes from the pipeline's
# secret (TF_VAR_ocpp_database_url), never from this file.
ocpp_tenants = ["public", "eosgie"]
