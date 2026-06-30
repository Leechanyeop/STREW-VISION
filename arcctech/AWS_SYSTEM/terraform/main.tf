terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } }
}
provider "aws" { region = var.aws_region }

data "aws_availability_zones" "available" { state = "available" }
resource "aws_vpc" "main" { cidr_block = "10.40.0.0/16" enable_dns_hostnames = true tags = { Name = var.project_name } }
resource "aws_subnet" "public" { count = 2 vpc_id = aws_vpc.main.id cidr_block = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index) availability_zone = data.aws_availability_zones.available.names[count.index] map_public_ip_on_launch = true }
resource "aws_internet_gateway" "igw" { vpc_id = aws_vpc.main.id }
resource "aws_route_table" "public" { vpc_id = aws_vpc.main.id route { cidr_block = "0.0.0.0/0" gateway_id = aws_internet_gateway.igw.id } }
resource "aws_route_table_association" "public" { count = 2 subnet_id = aws_subnet.public[count.index].id route_table_id = aws_route_table.public.id }
resource "aws_dynamodb_table" "events" { name = "${var.project_name}-events" billing_mode = "PAY_PER_REQUEST" hash_key = "pk" range_key = "sk" attribute { name = "pk" type = "S" } attribute { name = "sk" type = "S" } }
resource "aws_cloudwatch_log_group" "api" { name = "/ecs/${var.project_name}-api" retention_in_days = 14 }
resource "aws_iam_role" "task_exec" { name = "${var.project_name}-task-exec" assume_role_policy = jsonencode({ Version="2012-10-17", Statement=[{ Action="sts:AssumeRole", Effect="Allow", Principal={ Service="ecs-tasks.amazonaws.com" }}] }) }
resource "aws_iam_role_policy_attachment" "task_exec" { role = aws_iam_role.task_exec.name policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" }
resource "aws_iam_role" "task" { name = "${var.project_name}-task" assume_role_policy = aws_iam_role.task_exec.assume_role_policy }
resource "aws_iam_role_policy" "dynamo" { role = aws_iam_role.task.id policy = jsonencode({ Version="2012-10-17", Statement=[{ Effect="Allow", Action=["dynamodb:PutItem","dynamodb:Query","dynamodb:Scan"], Resource=aws_dynamodb_table.events.arn }] }) }
resource "aws_security_group" "alb" { name = "${var.project_name}-alb" vpc_id = aws_vpc.main.id ingress { from_port=80 to_port=80 protocol="tcp" cidr_blocks=["0.0.0.0/0"] } egress { from_port=0 to_port=0 protocol="-1" cidr_blocks=["0.0.0.0/0"] } }
resource "aws_security_group" "ecs" { name = "${var.project_name}-ecs" vpc_id = aws_vpc.main.id ingress { from_port=8000 to_port=8000 protocol="tcp" security_groups=[aws_security_group.alb.id] } egress { from_port=0 to_port=0 protocol="-1" cidr_blocks=["0.0.0.0/0"] } }
resource "aws_lb" "api" { name = "${var.project_name}-alb" load_balancer_type = "application" subnets = aws_subnet.public[*].id security_groups = [aws_security_group.alb.id] }
resource "aws_lb_target_group" "api" { name = "${var.project_name}-tg" port = 8000 protocol = "HTTP" vpc_id = aws_vpc.main.id target_type = "ip" health_check { path = "/health" matcher = "200" } }
resource "aws_lb_listener" "http" { load_balancer_arn = aws_lb.api.arn port = 80 protocol = "HTTP" default_action { type = "forward" target_group_arn = aws_lb_target_group.api.arn } }
resource "aws_ecs_cluster" "main" { name = "${var.project_name}-cluster" }
resource "aws_ecs_task_definition" "api" { family = "${var.project_name}-api" network_mode = "awsvpc" requires_compatibilities = ["FARGATE"] cpu = 256 memory = 512 execution_role_arn = aws_iam_role.task_exec.arn task_role_arn = aws_iam_role.task.arn container_definitions = jsonencode([{ name="api", image=var.container_image, essential=true, portMappings=[{ containerPort=8000, hostPort=8000 }], environment=[{name="ENV",value="aws"},{name="STORAGE_BACKEND",value="dynamodb"},{name="AWS_REGION",value=var.aws_region},{name="DYNAMODB_TABLE",value=aws_dynamodb_table.events.name},{name="API_KEY",value=var.api_key}], logConfiguration={ logDriver="awslogs", options={ awslogs-group=aws_cloudwatch_log_group.api.name, awslogs-region=var.aws_region, awslogs-stream-prefix="ecs" } } }]) }
resource "aws_ecs_service" "api" { name = "${var.project_name}-api" cluster = aws_ecs_cluster.main.id task_definition = aws_ecs_task_definition.api.arn desired_count = 1 launch_type = "FARGATE" network_configuration { subnets = aws_subnet.public[*].id security_groups = [aws_security_group.ecs.id] assign_public_ip = true } load_balancer { target_group_arn = aws_lb_target_group.api.arn container_name = "api" container_port = 8000 } depends_on = [aws_lb_listener.http] }
