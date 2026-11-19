terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.9"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state: create the storage account once by hand (or with a bootstrap module) and uncomment.
  # backend "azurerm" {
  #   resource_group_name  = "rg-swish-tfstate"
  #   storage_account_name = "swishtfstate"
  #   container_name       = "tfstate"
  #   key                  = "customer-service-diagnostics.tfstate"
  # }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}
