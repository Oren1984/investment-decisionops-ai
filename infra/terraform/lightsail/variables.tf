variable "aws_region" {
  description = "Lightsail region. Frankfurt by default (plan §19.3)."
  type        = string
  default     = "eu-central-1"
}

variable "availability_zone" {
  description = "Availability zone for the instance and the optional data disk."
  type        = string
  default     = "eu-central-1a"
}

variable "name" {
  description = "Name prefix for all Lightsail resources."
  type        = string
  default     = "decisionops"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,40}$", var.name))
    error_message = "Use lowercase letters, digits and hyphens (2-41 characters, starting with a letter)."
  }
}

variable "bundle_id" {
  description = "Lightsail bundle. medium_3_0 = 2 vCPU / 4 GB / 80 GB SSD (verify with `aws lightsail get-bundles` before applying)."
  type        = string
  default     = "medium_3_0"
}

variable "blueprint_id" {
  description = "OS blueprint (Ubuntu LTS). Verify with `aws lightsail get-blueprints` before applying."
  type        = string
  default     = "ubuntu_24_04"
}

variable "ssh_public_key" {
  description = "Owner's SSH public key (public part only, e.g. the contents of id_ed25519.pub)."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) ", var.ssh_public_key))
    error_message = "Provide an OpenSSH public key (ssh-ed25519, ssh-rsa or ecdsa-sha2-nistp256)."
  }
}

variable "ssh_allowed_cidrs" {
  description = "IPv4 CIDRs allowed to reach SSH (port 22). The owner's addresses only."
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidrs) > 0 && alltrue([for c in var.ssh_allowed_cidrs : can(cidrhost(c, 0)) && c != "0.0.0.0/0"])
    error_message = "List at least one valid IPv4 CIDR; 0.0.0.0/0 is not allowed for SSH."
  }
}

variable "deploy_user" {
  description = "Non-root user created by the launch script; owns the app checkout and runs Docker Compose."
  type        = string
  default     = "deploy"
}

variable "auto_snapshot_time" {
  description = "Daily automatic snapshot time (UTC, HH:00). Lightsail keeps the last 7."
  type        = string
  default     = "02:00"

  validation {
    condition     = can(regex("^([01][0-9]|2[0-3]):00$", var.auto_snapshot_time))
    error_message = "Use HH:00 in UTC."
  }
}

variable "data_disk_size_gb" {
  description = "Optional block disk for Docker volumes, in GB. 0 = no extra disk (the bundle's SSD is used)."
  type        = number
  default     = 0

  validation {
    condition     = var.data_disk_size_gb == 0 || (var.data_disk_size_gb >= 8 && var.data_disk_size_gb <= 16384)
    error_message = "Use 0 (no disk) or 8-16384 GB."
  }
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project    = "investment-decisionops-ai"
    managed_by = "terraform"
  }
}
