output "static_ip" {
  description = "Public IPv4 address. Point the owner's domain (A record) here."
  value       = aws_lightsail_static_ip.app.ip_address
}

output "instance_name" {
  description = "Lightsail instance name."
  value       = aws_lightsail_instance.app.name
}

output "ssh_command" {
  description = "SSH as the deploy user (key-only; password login is disabled by the launch script)."
  value       = "ssh ${var.deploy_user}@${aws_lightsail_static_ip.app.ip_address}"
}

output "data_disk" {
  description = "Data disk name, or null when no disk was requested."
  value       = local.with_disk ? aws_lightsail_disk.data[0].name : null
}
