terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69"
    }
  }

  # State stays local and git-ignored (plan §19.4). It holds no secrets: the app's .env is copied over SSH.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
