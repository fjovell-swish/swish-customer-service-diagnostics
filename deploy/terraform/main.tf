locals {
  name = "${var.project}-${var.environment}"
  tags = merge({ project = var.project, environment = var.environment, managed_by = "terraform" }, var.tags)

  web_image = "${azurerm_container_registry.acr.login_server}/${var.project}-web:${var.image_tag}"
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# Observability

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

# Container registry + identity the app pulls with

resource "azurerm_container_registry" "acr" {
  name                = replace("acr${local.name}", "-", "")
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "apps" {
  name                = "id-${local.name}-apps"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}
