# Azure deployment (Terraform)

One resource group per environment (`rg-swishdiag-<env>`): a VNet, a Container Apps environment
with the `web` app and the `migrate` job (deploy/web.Dockerfile), a private Postgres for the app's
own data (support cases, users), its registry, the identity it pulls with, and its logs. api-ocpp's
existing Postgres is read through a read-only user.

Before the first apply:

1. A read-only user on api-ocpp's database (`SELECT` on every tenant schema), exported as
   `TF_VAR_ocpp_database_url` (the deploy workflow takes it from the environment secret
   `OCPP_DATABASE_URL`). Never put it in a tfvars file.
2. Network: allow `terraform output outbound_ip_addresses` in api-ocpp's Postgres firewall. (If
   that database is only reachable privately, peer `vnet-swishdiag-<env>` with its VNet;
   `vnet_address_space` must not overlap it.)
3. An auth proxy in front of the app (oauth2-proxy or the API gateway) that signs people in
   against the user service and forwards `X-Forwarded-User`, `X-Forwarded-Groups` and
   `X-Proxy-Secret: $(terraform output -raw proxy_secret)` (config/auth_proxy.py).
4. The remote state backend in providers.tf.

Then `deploy/scripts/bootstrap.sh staging`, and releases go through `.github/workflows/deploy.yaml`.
