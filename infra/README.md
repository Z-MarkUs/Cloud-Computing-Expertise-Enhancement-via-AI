# Azure Container Apps infrastructure

This directory contains a parameterized Bicep deployment for the application runtime. It creates a Container Apps environment, one Container App, a user-assigned managed identity, and a Log Analytics workspace with a daily ingestion cap enabled by default. It does **not** create Azure OpenAI or Azure AI Search resources, deploy models, populate an index, or prove that any Azure deployment has occurred.

## Security and reliability defaults

- HTTPS-only ingress; plain HTTP redirects to HTTPS.
- Non-secret configuration only in the template. Azure mode is designed for Microsoft Entra authentication through the user-assigned managed identity.
- Encrypted traffic and mTLS inside the Container Apps environment.
- Startup and liveness probes on `/healthz`, plus a mode-aware readiness probe on `/health/ready`. Demo mode proves its providers and corpus loaded; Azure mode validates configuration and can opt into a live Search probe.
- HTTP concurrency autoscaling, a single active revision, and bounded inactive revision retention.
- Container stdout/stderr shipped to Log Analytics with retention and daily-ingestion controls.
- Optional CIDR ingress allow-list through `allowedIpRanges`.
- No registry password, API key, connection string, or other credential in Bicep parameters or outputs.

The template leaves public network access enabled for Log Analytics ingestion/query and exposes the app by default. A production environment with private networking needs a delegated subnet, private endpoints, DNS, and an access path for operators; those organization-specific controls are intentionally outside this portable showcase template.

## Validate without deploying

Install the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) and Bicep CLI, then compile both the template and example parameters:

```powershell
az bicep install
az bicep build --file infra/main.bicep
az bicep build-params --file infra/environments/dev.bicepparam
```

Compilation is also enforced by `.github/workflows/ci.yml`. It checks syntax and types but does not contact Azure or create resources.

## Preview and deploy deliberately

Use a dedicated resource group. `what-if` previews the resource changes and is the required review step before `create`:

```powershell
$cloudTutorLocation = 'eastasia'
$cloudTutorResourceGroup = 'rg-cloud-tutor-dev'
$cloudTutorDeployment = 'cloud-tutor-dev'

az group create --name $cloudTutorResourceGroup --location $cloudTutorLocation

az deployment group what-if `
  --name $cloudTutorDeployment `
  --resource-group $cloudTutorResourceGroup `
  --template-file infra/main.bicep `
  --parameters infra/environments/dev.bicepparam

az deployment group create `
  --name $cloudTutorDeployment `
  --resource-group $cloudTutorResourceGroup `
  --template-file infra/main.bicep `
  --parameters infra/environments/dev.bicepparam
```

The example points at the `main` GHCR tag. For a controlled environment, override `containerImage` with a release tag or, preferably, an OCI digest. Ensure the GHCR package is public before using it directly. A private Azure Container Registry should use the Container App identity plus the least-privilege `AcrPull` role, not a registry password.

## Enable the Azure provider

Set `cloudTutorMode = 'azure'` and provide the five required non-secret values in a separate environment parameter file:

```bicep
param cloudTutorMode = 'azure'
param azureOpenAIEndpoint = 'https://<account>.openai.azure.com/'
param azureChatDeployment = '<chat-deployment>'
param azureEmbeddingDeployment = '<embedding-deployment>'
param azureSearchEndpoint = 'https://<service>.search.windows.net'
param azureSearchIndex = '<index-name>'
```

After deployment, grant the template's `managedIdentityPrincipalId` only the data-plane roles it needs. The caller creating role assignments needs Owner or User Access Administrator rights:

```powershell
$cloudTutorIdentityObjectId = az deployment group show `
  --name $cloudTutorDeployment `
  --resource-group $cloudTutorResourceGroup `
  --query properties.outputs.managedIdentityPrincipalId.value `
  --output tsv

az role assignment create `
  --assignee-object-id $cloudTutorIdentityObjectId `
  --assignee-principal-type ServicePrincipal `
  --role 'Cognitive Services OpenAI User' `
  --scope '<azure-openai-resource-id>'

az role assignment create `
  --assignee-object-id $cloudTutorIdentityObjectId `
  --assignee-principal-type ServicePrincipal `
  --role 'Search Index Data Reader' `
  --scope '<azure-ai-search-resource-id>'
```

Azure AI Search must have role-based data-plane access enabled. Role propagation can take several minutes. The application uses `AZURE_CLIENT_ID`, injected by Bicep, to select its user-assigned identity.

If an external service forces key authentication, store the key in Azure Key Vault, grant the identity `Key Vault Secrets User`, and configure a Container Apps Key Vault secret reference. Never put a key in a `.bicepparam` file or a GitHub Actions variable.

## Observe the app

The deployment outputs the HTTPS URL and Log Analytics workspace resource ID. Useful Container Apps queries include:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "cloud-tutor-dev"
| project TimeGenerated, RevisionName_s, Log_s
| order by TimeGenerated desc
```

Application metrics remain available at `/metrics`. Put that endpoint behind an authenticated collector before using it for a public production service.
