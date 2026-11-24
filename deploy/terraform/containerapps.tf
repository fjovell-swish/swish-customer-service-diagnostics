# Azure Container Apps: one environment on the VNet, from the one image (docker/Dockerfile):
#
#   web       external ingress behind the auth proxy, gunicorn
#   migrate   manual job, `migrate --noinput`, run by deploy/scripts/deploy.sh before every rollout
#
# Cases and users go to this app's Postgres (postgres.tf); api-ocpp's database is read-only.

resource "random_password" "django_secret" {
  length  = 50
  special = false
}

# Shared between the auth proxy in front of the app and the app: it trusts the proxy's identity
# headers only when this comes with them (config/auth_proxy.py).
resource "random_password" "proxy_secret" {
  length  = 48
  special = false
}

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id   = azurerm_subnet.apps.id
  tags                       = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

locals {
  host = var.custom_domain != "" ? var.custom_domain : "ca-${local.name}-web.${azurerm_container_app_environment.env.default_domain}"

  # Only the values that are set become secrets (Container Apps refuses empty ones).
  secret_values = {
    "django-secret-key" = { env = "SECRET_KEY", value = random_password.django_secret.result }
    "proxy-secret"      = { env = "AUTH_PROXY_SECRET", value = random_password.proxy_secret.result }
    "database-url"      = { env = "DATABASE_URL", value = local.database_url }
    "ocpp-database-url" = { env = "OCPP_DATABASE_URL", value = var.ocpp_database_url }
    "gateway-db-url"    = { env = "GATEWAY_DATABASE_URL", value = var.gateway_database_url }
    "gireve-db-url"     = { env = "GIREVE_DATABASE_URL", value = var.gireve_database_url }
    "sentry-dsn"        = { env = "SENTRY_DSN", value = var.sentry_dsn }
    "github-token"      = { env = "GITHUB_TOKEN", value = var.github_token }
    "anthropic-api-key" = { env = "ANTHROPIC_API_KEY", value = var.anthropic_api_key }
    "jira-email"        = { env = "JIRA_EMAIL", value = var.jira_email }
    "jira-api-token"    = { env = "JIRA_API_TOKEN", value = var.jira_api_token }
  }
  secrets = { for k, v in local.secret_values : k => v if v.value != "" }

  # The deployments page reads each cluster's kubeconfig from a file: the secrets volume mounts
  # every secret at /secrets/<name>; KUBECONFIG_<CLUSTER> points at that cluster's.
  # Cluster names aren't secret: only the kubeconfigs stay sensitive (for_each refuses sensitive
  # keys). The deploy workflow passes every cluster; one whose secret is unset comes in empty.
  kubeconfig_clusters = nonsensitive([for cluster, kubeconfig in var.kubeconfigs : cluster if kubeconfig != ""])
  kubeconfig_secrets  = { for cluster in local.kubeconfig_clusters : "kubeconfig-${cluster}" => var.kubeconfigs[cluster] }
  kubeconfig_env      = { for cluster in local.kubeconfig_clusters : "KUBECONFIG_${upper(replace(cluster, "-", "_"))}" => "/secrets/kubeconfig-${cluster}" }

  env = {
    DJANGO_SETTINGS_MODULE      = "config.settings.production"
    ENVIRONMENT                 = var.environment
    IMAGE_TAG                   = var.image_tag
    LOG_FORMAT                  = "json"
    OCPP_TENANTS                = join(",", var.ocpp_tenants)
    AUTH_PROXY_DATA_GROUPS      = join(",", var.data_groups)
    AUTH_PROXY_SUPPORT_GROUPS   = join(",", var.support_groups)
    DJANGO_ALLOWED_HOSTS        = join(",", compact(["ca-${local.name}-web.${azurerm_container_app_environment.env.default_domain}", var.custom_domain]))
    DJANGO_CSRF_TRUSTED_ORIGINS = "https://${local.host}"
  }
}

resource "azurerm_container_app" "web" {
  name                         = "ca-${local.name}-web"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }
  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }
  dynamic "secret" {
    for_each = local.secrets
    content {
      name  = secret.key
      value = secret.value.value
    }
  }
  dynamic "secret" {
    for_each = local.kubeconfig_secrets
    content {
      name  = secret.key
      value = secret.value
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    dynamic "volume" {
      for_each = length(local.kubeconfig_clusters) > 0 ? ["secrets"] : []
      content {
        name         = volume.value
        storage_type = "Secret"
      }
    }

    container {
      name   = "web"
      image  = local.web_image
      cpu    = 0.25
      memory = "0.5Gi"

      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }
      dynamic "env" {
        for_each = local.kubeconfig_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "volume_mounts" {
        for_each = length(local.kubeconfig_clusters) > 0 ? ["secrets"] : []
        content {
          name = volume_mounts.value
          path = "/secrets"
        }
      }

      liveness_probe {
        transport        = "HTTP"
        port             = 8000
        path             = "/healthz"
        interval_seconds = 15
      }
      readiness_probe {
        transport        = "HTTP"
        port             = 8000
        path             = "/healthz"
        interval_seconds = 5
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

# Migrations, as a manual job on the new image before the app rolls (deploy/scripts/migrate.sh).

resource "azurerm_container_app_job" "migrate" {
  name                         = "caj-${local.name}-migrate"
  location                     = azurerm_resource_group.rg.location
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }
  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }
  dynamic "secret" {
    for_each = local.secrets
    content {
      name  = secret.key
      value = secret.value.value
    }
  }

  template {
    container {
      name   = "migrate"
      image  = local.web_image
      cpu    = 0.25
      memory = "0.5Gi"
      args   = ["migrate"]

      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets
        content {
          name        = env.value.env
          secret_name = env.key
        }
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}
