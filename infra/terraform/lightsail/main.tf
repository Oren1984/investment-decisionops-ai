locals {
  with_disk = var.data_disk_size_gb > 0
  # Lightsail attaches the disk at this path; on Nitro instances it appears as an NVMe device (the script handles both).
  disk_path = "/dev/xvdf"
}

resource "aws_lightsail_key_pair" "owner" {
  name       = "${var.name}-owner"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "app" {
  name              = var.name
  availability_zone = var.availability_zone
  blueprint_id      = var.blueprint_id
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.owner.name

  user_data = templatefile("${path.module}/launch.sh.tftpl", {
    deploy_user = var.deploy_user
    with_disk   = local.with_disk
  })

  add_on {
    type          = "AutoSnapshot"
    snapshot_time = var.auto_snapshot_time
    status        = "Enabled"
  }
}

resource "aws_lightsail_static_ip" "app" {
  name = "${var.name}-ip"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  static_ip_name = aws_lightsail_static_ip.app.name
  instance_name  = aws_lightsail_instance.app.name
}

# Replaces the instance's whole firewall: only HTTP/HTTPS are public; SSH only from the owner's CIDRs.
resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol   = "tcp"
    from_port  = 80
    to_port    = 80
    cidrs      = ["0.0.0.0/0"]
    ipv6_cidrs = ["::/0"]
  }

  port_info {
    protocol   = "tcp"
    from_port  = 443
    to_port    = 443
    cidrs      = ["0.0.0.0/0"]
    ipv6_cidrs = ["::/0"]
  }

  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.ssh_allowed_cidrs
  }
}

resource "aws_lightsail_disk" "data" {
  count             = local.with_disk ? 1 : 0
  name              = "${var.name}-data"
  availability_zone = var.availability_zone
  size_in_gb        = var.data_disk_size_gb
}

resource "aws_lightsail_disk_attachment" "data" {
  count         = local.with_disk ? 1 : 0
  disk_name     = aws_lightsail_disk.data[0].name
  instance_name = aws_lightsail_instance.app.name
  disk_path     = local.disk_path
}
