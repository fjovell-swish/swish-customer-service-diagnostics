# Azure deployment (Terraform)

One resource group per environment (`rg-swishdiag-<env>`): a VNet, a Container Apps environment
with the `web` app and the `migrate` job (docker/Dockerfile), a private Postgres for the app's
own data (support cases, users), its registry, the identity it pulls with, and its logs. api-ocpp's
existing Postgres is read through a read-only user.

Before the first apply:

1. A read-only user on api-ocpp's database (`SELECT` on every tenant schema), exported as
   `TF_VAR_ocpp_database_url` (the deploy workflow takes it from the environment secret
   `OCPP_DATABASE_URL`). Never put it in a tfvars file.
2. Optional, for the `data` role's admin: read-only users on api-gateway's and api-gireve's
   databases (`TF_VAR_gateway_database_url`, `TF_VAR_gireve_database_url`; the workflow's
   secrets `GATEWAY_DATABASE_URL`, `GIREVE_DATABASE_URL`). A service left out has no tables in
   the admin.
3. Optional, for the deployments page: a GitHub token with read access to Actions and contents of
   the service repos (`TF_VAR_github_token`; secret `DEPLOYMENTS_GITHUB_TOKEN`), and a kubeconfig
   per cluster whose user can get deployments and list pods (`TF_VAR_kubeconfigs`, a map; secrets
   `KUBECONFIG_STAGING`, `KUBECONFIG_PRODUCTION`, `KUBECONFIG_CSMS_PRODUCTION`). Without them the
   page shows CI or that cluster as unknown.
4. Optional, for Claude's assessment of a case: a Claude API key (`TF_VAR_anthropic_api_key`;
   secret `ANTHROPIC_API_KEY`). For escalating a case to Jira: a Jira account and its API token
   (`TF_VAR_jira_email`, `TF_VAR_jira_api_token`; secrets `JIRA_EMAIL`, `JIRA_API_TOKEN`) that can
   create issues in the project (`ROT` by default, config/settings/base.py). Without them the
   buttons are hidden.
5. Network: allow `terraform output outbound_ip_addresses` in the services' Postgres firewalls.
   (If a database is only reachable privately, peer `vnet-swishdiag-<env>` with its VNet;
   `vnet_address_space` must not overlap it.)
6. An auth proxy in front of the app (oauth2-proxy or the API gateway) that signs people in
   against the user service and forwards `X-Forwarded-User`, `X-Forwarded-Groups` and
   `X-Proxy-Secret: $(terraform output -raw proxy_secret)` (config/auth_proxy.py). Its groups
   grant the roles: `data_groups` and `support_groups` in the tfvars. It must let `/mcp` (the MCP
   API) through without signing in: that path checks its own personal tokens (README.md).
7. The remote state backend in providers.tf.

Then `deploy/scripts/bootstrap.sh staging`, and releases go through `.github/workflows/deploy.yaml`.
