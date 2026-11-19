output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_id" {
  description = "Resource id; deploy/scripts/promote.sh imports images across registries with it"
  value       = azurerm_container_registry.acr.id
}

output "web_url" {
  value = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "outbound_ip_addresses" {
  description = "Allow these in api-ocpp's Postgres firewall"
  value       = azurerm_container_app.web.outbound_ip_addresses
}

output "proxy_secret" {
  description = "Configure the auth proxy to send it as X-Proxy-Secret on every request"
  value       = random_password.proxy_secret.result
  sensitive   = true
}
