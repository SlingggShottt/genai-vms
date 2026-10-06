# Kubernetes (minikube)

A kustomize base for the whole system and a `minikube` overlay. **Rendered and schema-checked, not
yet deployed to a cluster**: `kubectl kustomize … | kubeconform -strict -kubernetes-version 1.31.0`
passes for all 39 resources (`make k8s-check` does this for all three overlays), but nothing here has been applied to a running cluster, so expect to
fix things the first time (resource sizes, startup order, probes) — see "Not verified" below.

```text
deploy/k8s/
├── base/
│   ├── infra/      postgres · redis · qdrant · minio · kafka (KRaft) · mediamtx
│   ├── apps/       api · frontend · retrieval · reasoning · indexer · events · correlation · ingestion · perception
│   ├── jobs/       migrate (alembic upgrade head) · create-topics
│   └── ingress.yaml   nginx ingress → frontend (which proxies /api to the api service)
├── overlays/minikube/   secret generator, NodePort for RTSP, images never pulled, perception off
├── overlays/gpu/        a cluster with a GPU node: perception and an in-cluster Ollama ask for the GPU
└── overlays/host-gpu/   no GPU node: Ollama stays on a host machine, exposed to the pods as a Service
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

## GPU nodes (`overlays/gpu`)

For a cluster with an NVIDIA GPU node. Not applied anywhere yet; `make k8s-check` renders it and
validates the schema.

1. Install the NVIDIA driver and container toolkit on the node, then the
   [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin) (or the GPU Operator).
   `kubectl describe node <node>` should list `nvidia.com/gpu: 1` under Capacity.
2. Label the node with the role its GPU plays (`vms.io/gpu-role`):
   - `shared`: one GPU for perception **and** Ollama. Both pods ask for `nvidia.com/gpu: 1`, so the
     device plugin must advertise two (time-slicing; the plugin's config is
     `sharing.timeSlicing.resources: [{name: nvidia.com/gpu, replicas: 2}]`). Time-slicing shares
     the card but **not its memory**: on a 4 GB card the two processes still have to fit in VRAM
     together, which is what the GPU lease in `vms_common.llm` is for.
   - `perception` and `genai` on two different nodes (or two GPUs): no sharing needed.
3. Copy `overlays/gpu/secrets.env.example` to `secrets.env`, replace `OWNER` (and the tags) in
   `overlays/gpu/kustomization.yaml` with the registry the nodes pull from (`release.yml` publishes
   every image except perception, which you build and push yourself), then
   `kubectl kustomize --load-restrictor=LoadRestrictionsNone deploy/k8s/overlays/gpu | kubectl apply -f -`.
4. `kubectl -n vms logs job/ollama-pull -f` while it downloads the two models into the PVC.

Reasoning does not ask for a GPU: it calls Ollama through the gateway. It would only once the
fine-tuned adapters are served in-process (`hf_local`), which does not exist yet.

## No GPU node (`overlays/host-gpu`)

The documented fallback: the GPU machine runs Ollama outside the cluster (the Compose/host setup in
`deploy/demo/`, with `OLLAMA_HOST=0.0.0.0`), and the pods reach it as `http://ollama:11434`: a
`Service` with no selector and an `Endpoints` pointing at the machine (`overlays/host-gpu/host-ollama.yaml`;
change its documentation address `192.0.2.10`, or use the `ExternalName` form in the comment for a DNS
name). Perception is scaled to 0 there. It runs on the GPU machine and needs the cluster's Kafka and
MinIO, which are only reachable inside the cluster today (Kafka advertises its in-cluster name):
exposing them to a host is **not built**, so on this path perception is run against the Compose stack,
not the cluster.

## Autoscaling

`base/apps/indexer-hpa.yaml` scales the indexer from 1 to 3 on CPU (80 % of its 100m request). It needs
metrics-server (`minikube addons enable metrics-server`); without it the autoscaler reports
`<unknown>` and changes nothing. The daily report is **not** a CronJob: the reasoning worker queues
yesterday's report itself after `daily_report_hour` (06:00 site time, `daily_report_auto`) and skips a
day that is already scheduled, so a CronJob would only duplicate it.

## Not verified

- No cluster was available while writing this: the **manifests have never been applied**.
- Image build and first start of `retrieval` in a container (a 2.5 GB torch wheel, SigLIP and the
  text embedder download on first run into an `emptyDir`, so every pod restart downloads again —
  use a PVC for `/hf` if that matters).
- Kafka's advertised listener is the in-cluster name only; reaching it from the host needs a
  port-forward and a client that tolerates that.
- The HPA never scaled anything (it is rendered and schema-checked, like everything here), the `gpu`
  and `host-gpu` overlays never ran against a GPU or a host Ollama, network policies, observability in the
  cluster (the pods carry `prometheus.io/*` annotations; no Prometheus is deployed by this tree).
