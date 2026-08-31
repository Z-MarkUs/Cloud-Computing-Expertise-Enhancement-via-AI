targetScope = 'resourceGroup'

@description('Short lowercase workload name. Keep this stable because it forms Azure resource names.')
@minLength(3)
@maxLength(20)
param workloadName string = 'cloud-tutor'

@description('Azure region for all resources in this deployment.')
param location string = resourceGroup().location

@description('Immutable OCI image reference. Prefer a digest or a version tag over latest.')
@minLength(1)
param containerImage string

@description('Runtime provider. Demo mode is self-contained; Azure mode requires all Azure endpoint and deployment parameters.')
@allowed([
  'demo'
  'azure'
])
param cloudTutorMode string = 'demo'

@description('Port exposed by the application container.')
@minValue(1)
@maxValue(65535)
param containerPort int = 8000

@description('Minimum replicas. Set to zero for scale-to-zero or at least one to avoid cold starts.')
@minValue(0)
@maxValue(30)
param minReplicas int = 0

@description('Maximum replicas for HTTP autoscaling.')
@minValue(1)
@maxValue(30)
param maxReplicas int = 3

@description('Concurrent HTTP requests per replica before scaling out.')
@minValue(1)
@maxValue(1000)
param targetConcurrentRequests int = 20

@description('Container CPU allocation in vCPU.')
@allowed([
  '0.25'
  '0.5'
  '0.75'
  '1.0'
  '1.25'
  '1.5'
  '1.75'
  '2.0'
])
param containerCpu string = '0.5'

@description('Container memory allocation. The value must be valid for the chosen CPU allocation.')
@allowed([
  '0.5Gi'
  '1Gi'
  '1.5Gi'
  '2Gi'
  '3Gi'
  '3.5Gi'
  '4Gi'
])
param containerMemory string = '1Gi'

@description('Whether the application receives a public HTTPS endpoint.')
param externalIngress bool = true

@description('Optional CIDR allow-list for ingress. An empty array permits all sources; any entries switch ingress to allow-list behavior.')
param allowedIpRanges array = []

@description('Browser origins accepted by application-level CORS. Same-origin traffic does not require an entry.')
param corsOrigins array = []

@description('Log Analytics data retention in days.')
@allowed([
  30
  60
  90
  120
  180
  270
  365
  550
  730
])
param logRetentionDays int = 30

@description('Daily Log Analytics ingestion cap in GB. Use -1 for no cap.')
@allowed([
  -1
  1
  5
  10
])
param logDailyQuotaGb int = 1

@description('Azure OpenAI endpoint. Required only when cloudTutorMode is azure.')
param azureOpenAIEndpoint string = ''

@description('Azure OpenAI chat model deployment name. Required only when cloudTutorMode is azure.')
param azureChatDeployment string = ''

@description('Azure OpenAI embedding model deployment name. Required only when cloudTutorMode is azure.')
param azureEmbeddingDeployment string = ''

@description('Azure AI Search endpoint. Required only when cloudTutorMode is azure.')
param azureSearchEndpoint string = ''

@description('Azure AI Search index name. Required only when cloudTutorMode is azure.')
param azureSearchIndex string = ''

@description('Optional Azure AI Search semantic configuration name.')
param azureSearchSemanticConfiguration string = ''

@description('Additional non-secret container environment variables in { name, value } form. Store secrets in Key Vault instead of this parameter.')
param additionalEnvironmentVariables array = []

@description('Resource tags merged over the deployment defaults.')
param tags object = {}

var environmentName = '${workloadName}-env'
var identityName = '${workloadName}-identity'
var logWorkspaceName = '${workloadName}-logs-${uniqueString(resourceGroup().id)}'
var resourceTags = union({
  application: 'cloud-computing-expertise-tutor'
  environment: 'showcase'
  managedBy: 'bicep'
}, tags)

var baseEnvironmentVariables = [
  {
    name: 'CLOUD_TUTOR_ENVIRONMENT'
    value: 'production'
  }
  {
    name: 'CLOUD_TUTOR_MODE'
    value: cloudTutorMode
  }
  {
    name: 'CLOUD_TUTOR_LOG_LEVEL'
    value: 'INFO'
  }
  {
    name: 'CLOUD_TUTOR_PORT'
    value: string(containerPort)
  }
  {
    name: 'FRONTEND_DIST_DIR'
    value: '/app/frontend/dist'
  }
  {
    name: 'AZURE_CLIENT_ID'
    value: workloadIdentity.properties.clientId
  }
]

var corsEnvironmentVariables = !empty(corsOrigins) ? [
  {
    name: 'CLOUD_TUTOR_CORS_ORIGINS'
    value: join(corsOrigins, ',')
  }
] : []

var azureEnvironmentVariables = cloudTutorMode == 'azure' ? concat([
  {
    name: 'CLOUD_TUTOR_AZURE_OPENAI_ENDPOINT'
    value: azureOpenAIEndpoint
  }
  {
    name: 'CLOUD_TUTOR_AZURE_CHAT_DEPLOYMENT'
    value: azureChatDeployment
  }
  {
    name: 'CLOUD_TUTOR_AZURE_EMBEDDING_DEPLOYMENT'
    value: azureEmbeddingDeployment
  }
  {
    name: 'CLOUD_TUTOR_AZURE_SEARCH_ENDPOINT'
    value: azureSearchEndpoint
  }
  {
    name: 'CLOUD_TUTOR_AZURE_SEARCH_INDEX'
    value: azureSearchIndex
  }
], !empty(azureSearchSemanticConfiguration) ? [
  {
    name: 'CLOUD_TUTOR_AZURE_SEARCH_SEMANTIC_CONFIGURATION'
    value: azureSearchSemanticConfiguration
  }
] : []) : []

var containerEnvironmentVariables = concat(
  baseEnvironmentVariables,
  corsEnvironmentVariables,
  azureEnvironmentVariables,
  additionalEnvironmentVariables
)

resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: logWorkspaceName
  location: location
  tags: resourceTags
  properties: {
    retentionInDays: logRetentionDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    workspaceCapping: {
      dailyQuotaGb: logDailyQuotaGb
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: resourceTags
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: resourceTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logWorkspace.properties.customerId
        sharedKey: logWorkspace.listKeys().primarySharedKey
      }
    }
    peerAuthentication: {
      mtls: {
        enabled: true
      }
    }
    peerTrafficConfiguration: {
      encryption: {
        enabled: true
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: workloadName
  location: location
  tags: resourceTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workloadIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      identitySettings: [
        {
          identity: workloadIdentity.id
          lifecycle: 'All'
        }
      ]
      ingress: {
        external: externalIngress
        allowInsecure: false
        clientCertificateMode: 'ignore'
        targetPort: containerPort
        transport: 'auto'
        ipSecurityRestrictions: [for (cidr, index) in allowedIpRanges: {
          name: 'allow-${index}'
          description: 'Approved ingress range ${index + 1}'
          action: 'Allow'
          ipAddressRange: cidr
        }]
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      terminationGracePeriodSeconds: 30
      containers: [
        {
          name: 'app'
          image: containerImage
          env: containerEnvironmentVariables
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/healthz'
                port: containerPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 1
              periodSeconds: 5
              timeoutSeconds: 3
              failureThreshold: 10
              successThreshold: 1
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: containerPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 3
              failureThreshold: 3
              successThreshold: 1
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: containerPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 3
              failureThreshold: 3
              successThreshold: 1
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-concurrency'
            http: {
              metadata: {
                concurrentRequests: string(targetConcurrentRequests)
              }
            }
          }
        ]
      }
    }
  }
}

output containerAppName string = containerApp.name
output containerAppResourceId string = containerApp.id
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output managedIdentityResourceId string = workloadIdentity.id
output managedIdentityClientId string = workloadIdentity.properties.clientId
output managedIdentityPrincipalId string = workloadIdentity.properties.principalId
output logAnalyticsWorkspaceId string = logWorkspace.id
