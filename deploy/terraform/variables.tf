variable "project" {
  description = "Short name used as a prefix for every resource (Container App names are limited to 32 characters)"
  type        = string
  default     = "swishdiag"
}

variable "environment" {
  description = "Deployment environment: dev, staging, production"
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "westeurope"
}

variable "image_tag" {
  description = "Image tag of the web image (a release tag such as v1.4.0, or a git SHA)"
  type        = string
  default     = "latest"
}

variable "min_replicas" {
  type    = number
  default = 1
}

variable "max_replicas" {
  type    = number
  default = 2
}

variable "custom_domain" {
  description = "Optional hostname, e.g. diagnostics.swish.example. Leave empty to use the Container Apps default FQDN"
  type        = string
  default     = ""
}

variable "data_groups" {
  description = "Groups (the auth proxy's groups header) that may query the data: tables and deployments"
  type        = list(string)
  default     = ["swish-data", "swish-ops"]
}

variable "support_groups" {
  description = "Groups (the auth proxy's groups header) that work in customer service: diagnostics and cases"
  type        = list(string)
  default     = ["swish-support", "swish-ops"]
}

variable "github_token" {
  description = "Read access to Actions and contents of the service repos, for the deployments page; empty: CI shows as unknown"
  type        = string
  default     = ""
  sensitive   = true
}

variable "kubeconfigs" {
  description = "Kubeconfig per cluster (staging, production, csms-production) whose user can get deployments and list pods, for the deployments page"
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "ocpp_database_url" {
  description = "api-ocpp's Postgres as a READ-ONLY user: postgres://user:password@host:5432/db. From TF_VAR_ocpp_database_url, never a tfvars file"
  type        = string
  sensitive   = true
}

variable "ocpp_tenants" {
  description = "api-ocpp's tenant schemas (its TENANT_SCHEMAS)"
  type        = list(string)
  default     = ["public"]
}

variable "vnet_address_space" {
  description = "The app's VNet; must not overlap anything it may be peered with"
  type        = string
  default     = "10.41.0.0/16"
}

variable "postgres_sku" {
  description = "Flexible Server SKU for the app's own database (cases, users)"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  type    = number
  default = 32768
}

variable "postgres_admin_user" {
  type    = string
  default = "swishdiag"
}

variable "sentry_dsn" {
  description = "Sentry DSN; empty disables Sentry"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
