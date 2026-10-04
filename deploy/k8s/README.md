# Kubernetes (minikube)

A kustomize base for the whole system and a `minikube` overlay. **Rendered and schema-checked, not
yet deployed to a cluster**: `kubectl kustomize … | kubeconform -strict -kubernetes-version 1.31.0`
passes for all 38 resources, but nothing here has been applied to a running cluster, so expect to
fix things the first time (resource sizes, startup order, probes) — see "Not verified" below.

```text
deploy/k8s/
├── base/
│   ├── infra/      postgres · redis · qdrant · minio · kafka (KRaft) · mediamtx
│   ├── apps/       api · frontend · retrieval · reasoning · indexer · events · correlation · ingestion · perception
│   ├── jobs/       migrate (alembic upgrade head) · create-topics
│   └── ingress.yaml   nginx ingress → frontend (which proxies /api to the api service)
└── overlays/minikube/   secret generator, NodePort for RTSP, images never pulled, perception off
```

One namespace, `vms` (the design sketches `vms-infra` / `vms-app` / `vms-obs`; separate namespaces
cost cross-namespace DNS names in every setting and bought nothing on a single laptop). Infra is plain
StatefulSets rather than Strimzi / CloudNativePG / Helm charts: a single broker and a single database
need no operator, and the manifests stay readable. Settings every service shares are the ConfigMap
`vms-env`; `config/*.yaml` (models, rules, correlation, VQA bank, cameras, zones) become the ConfigMap
`vms-config`; passwords and keys are the Secret `vms-secrets`, generated from a file you do not commit.

## Run it

```bash
minikube start --driver=docker --cpus=6 --memory=10g       # the stack wants ~8 GB
minikube addons enable ingress
cp deploy/k8s/overlays/minikube/secrets.env.example deploy/k8s/overlays/minikube/secrets.env   # edit
make k8s-up                  # builds the images into minikube's Docker, applies everything
kubectl -n vms get pods -w
minikube service -n vms frontend --url                      # or add an /etc/hosts entry for the ingress
make k8s-down
```

`make k8s-render` prints the manifests (the `config/` files sit outside this directory, so the build
needs `--load-restrictor=LoadRestrictionsNone`, which the target passes).

## The language model and the GPU

Ollama is **not** in the cluster: the pods call `http://host.minikube.internal:11434` (the laptop's
Ollama, started with `OLLAMA_HOST=0.0.0.0`). Perception is scaled to 0 in the minikube overlay because
passing the laptop's GPU into minikube through Docker is the fragile part; run it on the host
(`uv run --package vms-perception python -m perception.main`) against the cluster's Kafka and MinIO
(`kubectl port-forward`), or on a GPU node: label it `vms.io/gpu-role=perception`, install the NVIDIA
device plugin, and set perception's replicas back to 1 — the Deployment already asks for
`nvidia.com/gpu: 1`.

## Not verified

- No cluster was available while writing this: the **manifests have never been applied**.
- Image build and first start of `retrieval` in a container (a 2.5 GB torch wheel, SigLIP and the
  text embedder download on first run into an `emptyDir`, so every pod restart downloads again —
  use a PVC for `/hf` if that matters).
- Kafka's advertised listener is the in-cluster name only; reaching it from the host needs a
  port-forward and a client that tolerates that.
- Autoscaling (an HPA on the indexer was a stretch goal), network policies, observability in the
  cluster (the pods carry `prometheus.io/*` annotations; no Prometheus is deployed by this tree).
