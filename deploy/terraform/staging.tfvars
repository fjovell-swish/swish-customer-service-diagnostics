# Staging: every tagged release lands here first (see .github/workflows/deploy.yaml); production
# gets the same image once staging is healthy. Reads api-ocpp's STAGING database.
project     = "swishdiag"
environment = "staging"
location    = "westeurope"

min_replicas = 1
max_replicas = 1

# custom_domain = "diagnostics-staging.swish.example"
allowed_groups = ["swish-support", "swish-ops"]

# api-ocpp's TENANT_SCHEMAS on staging (central-system maps every staging host to public). The read-only connection URL comes from the pipeline's
# secret (TF_VAR_ocpp_database_url), never from this file.
ocpp_tenants = ["public"]
