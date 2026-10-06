#!/usr/bin/env bash
# Renders every overlay, validates it against the Kubernetes schema and asserts what each overlay is
# for. Nothing is applied to a cluster. Needs kubectl and kubeconform (`make k8s-check`).
#
# A rendered, schema-valid manifest is not a working deployment: this catches typos and the wrong
# fields, not a pod that never starts.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
K8S_VERSION="${K8S_VERSION:-1.31.0}"
tmp="$(mktemp -d)"
created=()
cleanup() {
  rm -rf "$tmp"
  [ "${#created[@]}" -eq 0 ] || rm -f "${created[@]}"
}
trap cleanup EXIT

fail=0
check() { # description, command...
  local what="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "  ok   $what"; else echo "  FAIL $what"; fail=1; fi
}

for overlay in minikube gpu host-gpu; do
  dir="deploy/k8s/overlays/$overlay"
  echo "== $overlay"
  # The secret file is not committed; render with the example's placeholder values.
  if [ ! -f "$dir/secrets.env" ]; then
    src="$dir/secrets.env.example"
    cp "$src" "$dir/secrets.env"
    created+=("$dir/secrets.env")
  fi
  out="$tmp/$overlay.yaml"
  kubectl kustomize --load-restrictor=LoadRestrictionsNone "$dir" >"$out"
  kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" "$out" | tail -1

  has() { grep -qE "$1" "$out"; }
  check "the indexer autoscaler is there" has '^kind: HorizontalPodAutoscaler'
  case "$overlay" in
    minikube)
      check "perception is scaled to 0 (no GPU in minikube)" \
        bash -c "awk '/^kind: Deployment/{d=1} d&&/name: perception$/{p=1} p&&/replicas:/{print; exit}' '$out' | grep -q 'replicas: 0'"
      check "pods use the laptop's Ollama" has 'VMS_LLM_OLLAMA_URL: http://host.minikube.internal:11434'
      ;;
    gpu)
      check "perception asks for a GPU" has 'nvidia.com/gpu: 1'
      check "perception is placed by vms.io/gpu-role (perception or shared)" has 'vms.io/gpu-role'
      check "perception has no leftover nodeSelector" bash -c "! grep -qE '^ +nodeSelector:' '$out'"
      check "an in-cluster Ollama Deployment exists" has '^  name: ollama$'
      check "pods use the in-cluster Ollama" has 'VMS_LLM_OLLAMA_URL: http://ollama:11434'
      check "images come from a registry" has 'image: ghcr.io/OWNER/genai-vms-api:latest'
      ;;
    host-gpu)
      check "the Ollama Service has Endpoints (the host)" has '^kind: Endpoints'
      check "pods use the Ollama Service" has 'VMS_LLM_OLLAMA_URL: http://ollama:11434'
      check "no Ollama Deployment (it runs on the host)" bash -c "! grep -q 'image: ollama/ollama' '$out'"
      check "perception is scaled to 0 (it runs on the GPU host)" \
        bash -c "awk '/^kind: Deployment/{d=1} d&&/name: perception$/{p=1} p&&/replicas:/{print; exit}' '$out' | grep -q 'replicas: 0'"
      ;;
  esac
done
[ "$fail" -eq 0 ] && echo "all overlays render and check out" || { echo "some checks failed" >&2; exit 1; }
