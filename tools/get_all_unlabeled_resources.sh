#!/usr/bin/env bash

# Script to find Kubernetes resources with specific keywords but WITHOUT their corresponding labels
# Compatible with bash 4+ and zsh

# Color codes
GREEN='\033[0;32m'      # Green for correct labels
RED='\033[0;31m'        # Red for missing labels (CLI gaps)
YELLOW='\033[0;33m'     # Yellow for service team concerns
BOLD='\033[1m'          # Bold for titles
RESET='\033[0m'         # Reset colors

echo -e "${BOLD}=== Finding resources with keywords but WITHOUT correct labels ===${RESET}"
echo ""

# Define keyword to label mappings
# Format: "keyword1|keyword2|keyword3:expected-label-value"
declare -A KEYWORD_LABEL_MAP=(
    ["mq|broker"]="microsoft-iotoperations-mqttbroker"
    ["opcua|opc"]="microsoft-iotoperations-opcuabroker"
    ["akri"]="microsoft-iotoperations-akri"
    ["dataflow"]="microsoft-iotoperations-dataflows"
    ["schema-registry|schema_registry|adr"]="microsoft-iotoperations-schemas"
    ["meso|observability"]="microsoft-iotoperations-observability"
)

# All valid AIO app.kubernetes.io/name label values.
# If a resource already has any of these, it is owned by another AIO service
# and should not be flagged as unlabeled (prevents cross-service name collision false positives).
VALID_AIO_LABELS=(
    "microsoft-iotoperations-mqttbroker"
    "microsoft-iotoperations-opcuabroker"
    "microsoft-iotoperations-akri"
    "microsoft-iotoperations-dataflows"
    "microsoft-iotoperations-schemas"
    "microsoft-iotoperations-observability"
    "microsoft-iotoperations-observability-cluster-metrics"
)

# Resources that are intentionally unlabeled or already captured via alternative means
# (e.g. cert-manager module, no diagnostic value). Format: "namespace/name".
# These are known gaps that do NOT need a CLI fix.
KNOWN_UNLABELED_EXCLUSIONS=(
    # Captured by cert-manager module; adding the common label is a service team task
    "azure-iot-operations/azure-iot-operations-observability-trust-bundle"
    # Bare serviceaccount with no diagnostic content
    "azure-iot-operations/mqtt-client"
)

# Get all resource types in the cluster
RESOURCE_TYPES=(
    "pods"
    "services"
    "deployments"
    "replicasets"
    "statefulsets"
    "daemonsets"
    "configmaps"
    # "secrets"
    "serviceaccounts"
    "persistentvolumeclaims"
    "jobs"
    "cronjobs"
    "ingresses"
    "networkpolicies"
    "validatingwebhookconfigurations"
    "mutatingwebhookconfigurations"
)

UNLABELED_RESOURCES=()
CRD_DEFINITION_VIOLATIONS=()

# Function to check if a name matches any keyword pattern
matches_keyword() {
    local name=$1
    local keywords=$2
    local name_lower=$(echo "${name}" | tr '[:upper:]' '[:lower:]')
    
    # Split keywords by | (compatible with both bash and zsh)
    IFS='|' read -ra keyword_array <<< "${keywords}"
    for keyword in "${keyword_array[@]}"; do
        if echo "${name_lower}" | grep -q "${keyword}"; then
            return 0
        fi
    done
    return 1
}

# Function to check if a label is valid for a resource
# Handles special cases where alternative labels are acceptable
is_label_valid() {
    local name=$1
    local label_value=$2
    local expected_label=$3
    local name_lower=$(echo "${name}" | tr '[:upper:]' '[:lower:]')

    # Check if it matches the expected label
    if [[ "${label_value}" == "${expected_label}" ]]; then
        return 0
    fi

    # If the resource already has any valid AIO label (just a different one), it is
    # owned by another AIO service — not a labeling gap, just a name collision.
    for valid_label in "${VALID_AIO_LABELS[@]}"; do
        if [[ "${label_value}" == "${valid_label}" ]]; then
            return 0
        fi
    done

    # Special case 1: 'observability-cluster-metrics' resources can have 'microsoft-iotoperations-observability-cluster-metrics' label
    if echo "${name_lower}" | grep -q "observability-cluster-metrics"; then
        if [[ "${label_value}" == "microsoft-iotoperations-observability-cluster-metrics" ]]; then
            return 0
        fi
    fi

    # Special case 2: 'akri-adr' resources can still have 'microsoft-iotoperations-akri' label
    if echo "${name_lower}" | grep -q "akri-adr"; then
        if [[ "${label_value}" == "microsoft-iotoperations-akri" ]]; then
            return 0
        fi
    fi

    # Special case 3: 'opc-ua-broker' or 'opc-opcuabroker' resources can have 'microsoft-iotoperations-opcuabroker' label
    if echo "${name_lower}" | grep -qE "opc-ua-broker|opc-opcuabroker"; then
        if [[ "${label_value}" == "microsoft-iotoperations-opcuabroker" ]]; then
            return 0
        fi
    fi

    return 1
}

# Function to check if a namespace/name pair is in the known exclusions list
is_excluded() {
    local namespace=$1
    local name=$2
    local key="${namespace}/${name}"
    for exclusion in "${KNOWN_UNLABELED_EXCLUSIONS[@]}"; do
        if [[ "${exclusion}" == "${key}" ]]; then
            return 0
        fi
    done
    return 1
}

# Check each keyword-label pair
# Compatible iteration over associative array keys (works in both bash and zsh)
for keywords_pattern in "${!KEYWORD_LABEL_MAP[@]}"; do
    expected_label="${KEYWORD_LABEL_MAP[$keywords_pattern]}"
    
    echo "========================================"
    echo -e "Checking resources with keywords: ${BOLD}${keywords_pattern}${RESET}"
    echo -e "Expected label: ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}"
    echo "========================================"
    echo ""
    
    for resource in "${RESOURCE_TYPES[@]}"; do
        echo "Checking ${resource}..."
        
        # Get all resources
        all_resources=$(kubectl get ${resource} --all-namespaces -o wide 2>/dev/null)
        
        if [[ $? -eq 0 ]] && [[ -n "${all_resources}" ]]; then
            # Check each line for matching keywords
            echo "${all_resources}" | tail -n +2 | while read -r line; do
                # Extract namespace and name from the line
                namespace=$(echo "${line}" | awk '{print $1}')
                name=$(echo "${line}" | awk '{print $2}')
                
                # Skip if empty
                if [[ -z "${namespace}" ]] || [[ -z "${name}" ]]; then
                    continue
                fi
                
                # Check if name matches any keyword in the pattern
                if matches_keyword "${name}" "${keywords_pattern}"; then
                    # Get labels for this specific resource
                    if [[ "${namespace}" == "" ]] || [[ "${namespace}" == "<none>" ]]; then
                        labels=$(kubectl get ${resource} ${name} -o jsonpath='{.metadata.labels}' 2>/dev/null)
                    else
                        labels=$(kubectl get ${resource} ${name} -n ${namespace} -o jsonpath='{.metadata.labels}' 2>/dev/null)
                    fi
                    
                    # Check if it has the correct label
                    label_value=$(echo "${labels}" | jq -r '.["app.kubernetes.io/name"] // "no-label"' 2>/dev/null)
                    
                    if is_label_valid "${name}" "${label_value}" "${expected_label}"; then
                        echo -e "  ${GREEN}✓ ${BOLD}${resource}${RESET}${GREEN} ${namespace}/${name} has correct label ${BOLD}app.kubernetes.io/name=${label_value}${RESET}"
                    elif is_excluded "${namespace}" "${name}"; then
                        echo -e "  ${GREEN}~ ${BOLD}${resource}${RESET}${GREEN} ${namespace}/${name} is a known exclusion (no label needed by CLI)${RESET}"
                    else
                        echo -e "  ${RED}✗ ${BOLD}${resource}${RESET}${RED} ${namespace}/${name} does NOT have label ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}${RED} (current: ${label_value})${RESET}"
                        UNLABELED_RESOURCES+=("${resource}\t${namespace}\t${name}\t${expected_label}\t${label_value}")
                    fi
                fi
            done
        fi
    done
    echo ""
    
    # Check CRDs
    # NOTE: CRD definition objects lacking app.kubernetes.io/name is a SERVICE TEAM concern.
    # CRD definitions are already captured by the support bundle via a separate CRD sweep
    # regardless of labels. Violations here do NOT indicate a CLI support bundle gap.
    echo "Checking Custom Resource Definitions (service team concern — not a CLI gap)..."
    all_crds=$(kubectl get crd 2>/dev/null)
    
    if [[ -n "${all_crds}" ]]; then
        echo "${all_crds}" | tail -n +2 | while read -r line; do
            # Extract CRD name
            crd_name=$(echo "${line}" | awk '{print $1}')
            
            # Skip if empty
            if [[ -z "${crd_name}" ]]; then
                continue
            fi
            
            # Check if name matches any keyword in the pattern
            if matches_keyword "${crd_name}" "${keywords_pattern}"; then
                # Get labels for this CRD
                labels=$(kubectl get crd ${crd_name} -o jsonpath='{.metadata.labels}' 2>/dev/null)
                label_value=$(echo "${labels}" | jq -r '.["app.kubernetes.io/name"] // "no-label"' 2>/dev/null)
                
                if is_label_valid "${crd_name}" "${label_value}" "${expected_label}"; then
                    echo -e "  ${GREEN}✓ ${BOLD}CRD${RESET}${GREEN} ${crd_name} has correct label ${BOLD}app.kubernetes.io/name=${label_value}${RESET}"
                else
                    echo -e "  ${YELLOW}! ${BOLD}CRD${RESET}${YELLOW} ${crd_name} does NOT have label ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}${YELLOW} (current: ${label_value}) [service team]${RESET}"
                    CRD_DEFINITION_VIOLATIONS+=("CustomResourceDefinition\tcluster-wide\t${crd_name}\t${expected_label}\t${label_value}")
                fi
            fi
        done
    fi
    echo ""
    
    # Check instances of all CRDs
    echo "Checking Custom Resource instances..."
    kubectl get crd -o name 2>/dev/null | while read crd; do
        crd_name=${crd#customresourcedefinition.apiextensions.k8s.io/}
        
        # Get all instances of this CRD
        all_instances=$(kubectl get ${crd_name} --all-namespaces 2>/dev/null)
        
        if [[ -n "${all_instances}" ]]; then
            echo "${all_instances}" | tail -n +2 | while read -r line; do
                # Extract namespace and name
                namespace=$(echo "${line}" | awk '{print $1}')
                name=$(echo "${line}" | awk '{print $2}')
                
                # Skip if empty
                if [[ -z "${namespace}" ]] || [[ -z "${name}" ]]; then
                    continue
                fi
                
                # Check if name matches any keyword in the pattern
                if matches_keyword "${name}" "${keywords_pattern}"; then
                    # Get labels for this instance
                    if [[ "${namespace}" == "" ]] || [[ "${namespace}" == "<none>" ]]; then
                        labels=$(kubectl get ${crd_name} ${name} -o jsonpath='{.metadata.labels}' 2>/dev/null)
                    else
                        labels=$(kubectl get ${crd_name} ${name} -n ${namespace} -o jsonpath='{.metadata.labels}' 2>/dev/null)
                    fi
                    
                    label_value=$(echo "${labels}" | jq -r '.["app.kubernetes.io/name"] // "no-label"' 2>/dev/null)
                    
                    if is_label_valid "${name}" "${label_value}" "${expected_label}"; then
                        echo -e "  ${GREEN}✓ ${BOLD}${crd_name}${RESET}${GREEN} ${namespace}/${name} has correct label ${BOLD}app.kubernetes.io/name=${label_value}${RESET}"
                    elif is_excluded "${namespace}" "${name}"; then
                        echo -e "  ${GREEN}~ ${BOLD}${crd_name}${RESET}${GREEN} ${namespace}/${name} is a known exclusion (no label needed by CLI)${RESET}"
                    else
                        echo -e "  ${RED}✗ ${BOLD}${crd_name}${RESET}${RED} ${namespace}/${name} does NOT have label ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}${RED} (current: ${label_value})${RESET}"
                        UNLABELED_RESOURCES+=("${crd_name}\t${namespace}\t${name}\t${expected_label}\t${label_value}")
                    fi
                fi
            done
        fi
    done
    echo ""
    echo ""
done

# Display final results
echo ""
echo "=========================================="
echo "=== FINAL RESULTS: CLI GAPS ==="
echo "=== (resources missing from support bundle) ==="
echo "=========================================="
echo ""

if [[ ${#UNLABELED_RESOURCES[@]} -eq 0 ]]; then
    echo -e "${GREEN}✓ No CLI gaps found! All runtime resources are captured by the support bundle.${RESET}"
else
    echo -e "${RED}Found ${BOLD}${#UNLABELED_RESOURCES[@]}${RESET}${RED} resource(s) missing from support bundle:${RESET}"
    echo ""
    for resource in "${UNLABELED_RESOURCES[@]}"; do
        IFS=$'\t' read -r kind namespace name expected_label current_label <<< "${resource}"
        echo -e "  ${BOLD}${namespace}/${name}${RESET} (${kind}) - Expected: ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}, Current: ${current_label}"
    done
    echo ""
fi

echo ""
echo "=========================================="
echo "=== SERVICE TEAM ACTION ITEMS ==="
echo "=== (CRD definitions missing label — not CLI gaps) ==="
echo "=========================================="
echo ""

if [[ ${#CRD_DEFINITION_VIOLATIONS[@]} -eq 0 ]]; then
    echo -e "${GREEN}✓ No CRD definition labeling issues found.${RESET}"
else
    echo -e "${YELLOW}Found ${BOLD}${#CRD_DEFINITION_VIOLATIONS[@]}${RESET}${YELLOW} CRD definition(s) missing the common label (service team to fix):${RESET}"
    echo ""
    for resource in "${CRD_DEFINITION_VIOLATIONS[@]}"; do
        IFS=$'\t' read -r kind namespace name expected_label current_label <<< "${resource}"
        echo -e "  ${BOLD}${name}${RESET} (${kind}) - Expected: ${BOLD}app.kubernetes.io/name=${expected_label}${RESET}, Current: ${current_label}"
    done
    echo ""
fi

echo ""
echo "=== Done ==="
