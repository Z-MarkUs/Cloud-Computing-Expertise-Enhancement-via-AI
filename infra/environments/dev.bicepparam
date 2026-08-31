using '../main.bicep'

param workloadName = 'cloud-tutor-dev'
param containerImage = 'ghcr.io/z-markus/cloud-computing-expertise-enhancement-via-ai:main'
param cloudTutorMode = 'demo'
param minReplicas = 0
param maxReplicas = 3
param logRetentionDays = 30
param logDailyQuotaGb = 1
param tags = {
  environment: 'development'
  owner: 'hehan-zhao'
  purpose: 'portfolio-showcase'
}
