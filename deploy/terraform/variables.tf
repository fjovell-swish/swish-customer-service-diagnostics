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

variable "allowed_groups" {
  description = "Groups (from the auth proxy's groups header) allowed in"
  type        = list(string)
  default     = ["swish-support", "swish-ops"]
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

variable "infrastructure_subnet_id" {
  description = "Optional subnet (delegated to Microsoft.App/environments) when api-ocpp's Postgres is only reachable privately"
  type        = string
  default     = ""
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
