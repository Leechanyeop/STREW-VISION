output "api_url" { value = "http://${aws_lb.api.dns_name}" }
output "dynamodb_table" { value = aws_dynamodb_table.events.name }
