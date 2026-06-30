param(
  [Parameter(Mandatory=$true)][string]$AwsAccountId,
  [string]$Region="ap-northeast-2",
  [string]$Repository="strew-robot-api",
  [string]$Tag="latest"
)
$ErrorActionPreference = "Stop"
$uri = "$AwsAccountId.dkr.ecr.$Region.amazonaws.com/$Repository`:$Tag"
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin "$AwsAccountId.dkr.ecr.$Region.amazonaws.com"
docker build -t $Repository`:$Tag .
docker tag $Repository`:$Tag $uri
docker push $uri
Write-Host "Pushed $uri"
