variable "project_name" { default = "strew-vision" }
variable "aws_region" { default = "ap-northeast-2" }
variable "container_image" { description = "ECR image URI" }
variable "api_key" { description = "API key shared by dashboard and Jetson" sensitive = true }
