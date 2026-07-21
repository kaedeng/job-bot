from __future__ import annotations

import re

# Canonical tech keywords extracted from job titles/descriptions at ingestion time.
# Covers CS (languages, frameworks, infra, data/ML, security, systems) and EE
# (hardware, embedded, analog, RF, power, signal processing, semiconductors).
# Ordered by category — doesn't affect correctness, just readability.
TECH_KEYWORDS: list[str] = [
    # ── Languages ────────────────────────────────────────────────────────────────
    "python", "java", "javascript", "typescript", "golang", "go", "rust",
    "c++", "c#", "c", "swift", "kotlin", "scala", "ruby", "php", "perl",
    "matlab", "r", "julia", "elixir", "erlang", "haskell", "ocaml", "f#",
    "clojure", "lisp", "scheme", "fortran", "cobol", "ada", "pascal",
    "lua", "dart", "groovy", "racket", "prolog", "assembly", "asm",
    "bash", "shell", "powershell", "zsh", "fish",
    "verilog", "vhdl", "systemverilog", "spice", "hspice",
    "solidity", "move", "cairo",
    # ── Web / Frontend ───────────────────────────────────────────────────────────
    "react", "angular", "vue", "svelte", "nextjs", "nuxtjs", "remix",
    "webpack", "vite", "rollup", "esbuild", "babel", "eslint",
    "html", "css", "sass", "scss", "less", "tailwind", "bootstrap",
    "redux", "zustand", "mobx", "recoil", "jotai",
    "graphql", "rest", "trpc", "websocket", "webrtc", "grpc",
    "jest", "vitest", "cypress", "playwright", "storybook",
    "react native", "ionic", "electron",
    # ── Backend / Frameworks ─────────────────────────────────────────────────────
    "node", "express", "fastapi", "django", "flask", "fastify",
    "spring", "spring boot", "quarkus", "micronaut", "dropwizard",
    "rails", "sinatra", "laravel", "symfony", "codeigniter",
    "gin", "fiber", "echo", "chi",
    "actix", "axum", "rocket", "warp",
    "phoenix", "plug", "ecto",
    "asp.net", "blazor", "wpf",
    # ── Mobile ───────────────────────────────────────────────────────────────────
    "ios", "android", "flutter", "swiftui", "jetpack compose",
    "xcode", "android studio", "expo",
    # ── Databases ────────────────────────────────────────────────────────────────
    "postgresql", "postgres", "mysql", "mariadb", "sqlite", "oracle",
    "sql server", "mssql", "cockroachdb", "tidb", "planetscale",
    "mongodb", "couchdb", "couchbase", "firestore", "dynamodb",
    "cassandra", "hbase", "scylladb",
    "redis", "memcached", "dragonfly",
    "elasticsearch", "opensearch", "solr", "meilisearch",
    "neo4j", "arangodb", "dgraph",
    "clickhouse", "druid", "pinot",
    "snowflake", "bigquery", "redshift", "databricks",
    "sql", "nosql", "orm", "prisma", "sqlalchemy", "hibernate",
    # ── Infrastructure / DevOps / Cloud ──────────────────────────────────────────
    "aws", "gcp", "azure", "cloudflare", "vercel", "netlify", "heroku",
    "docker", "kubernetes", "k8s", "helm", "kustomize", "istio", "envoy",
    "terraform", "pulumi", "cdk", "crossplane",
    "ansible", "puppet", "chef", "saltstack",
    "jenkins", "github actions", "gitlab ci", "circleci", "buildkite",
    "argocd", "flux", "spinnaker",
    "prometheus", "grafana", "datadog", "newrelic", "splunk", "pagerduty",
    "nginx", "apache", "haproxy", "traefik",
    "linux", "ubuntu", "debian", "centos", "rhel", "alpine",
    "ci/cd", "gitops", "sre", "devsecops",
    "git", "mercurial", "svn",
    "lambda", "fargate", "ec2", "s3", "rds", "sqs", "sns", "eks", "ecs",
    "gke", "cloud run", "cloud functions",
    "aks", "azure functions", "cosmos db",
    # ── Networking ───────────────────────────────────────────────────────────────
    "tcp/ip", "udp", "http", "https", "tls", "ssl", "dns", "dhcp",
    "bgp", "ospf", "mpls", "vlan", "vxlan", "sdn", "nfv",
    "firewall", "vpn", "load balancer", "cdn",
    "wireshark", "tcpdump", "nmap",
    "802.11", "wifi", "bluetooth", "zigbee", "z-wave", "lora", "lorawan",
    "ethernet", "can bus", "modbus", "profibus", "opc-ua",
    # ── Security / Cryptography ───────────────────────────────────────────────────
    "security", "cybersecurity", "appsec", "devsecops", "sast", "dast",
    "penetration testing", "pen testing", "red team", "blue team",
    "vulnerability", "cve", "owasp",
    "cryptography", "encryption", "aes", "rsa", "ecc", "sha", "hmac",
    "pki", "x.509", "oauth", "saml", "jwt", "oidc",
    "siem", "soc", "threat modeling", "zero trust",
    "burp suite", "metasploit", "nessus",
    "malware", "reverse engineering",
    # ── Operating Systems / Systems Programming ───────────────────────────────────
    "operating systems", "kernel", "drivers", "device drivers", "bsp",
    "rtos", "freertos", "zephyr", "vxworks", "threadx",
    "posix", "unix", "windows", "macos",
    "memory management", "virtual memory", "cache", "scheduler",
    "multithreading", "concurrency", "parallelism", "async", "coroutines",
    "ipc", "shared memory", "sockets", "pipes",
    "llvm", "gcc", "clang", "ld", "linker", "debugger", "gdb", "lldb",
    "profiling", "perf", "valgrind", "sanitizer",
    "elf", "dwarf", "abi",
    # ── Compilers / PLT ───────────────────────────────────────────────────────────
    "compiler", "interpreter", "jit", "aot", "bytecode", "ir",
    "lexer", "parser", "ast", "ssa", "cfg",
    "llvm", "mlir", "cranelift", "wasm", "webassembly",
    "type system", "type inference", "garbage collection",
    # ── Distributed Systems ───────────────────────────────────────────────────────
    "distributed systems", "consensus", "raft", "paxos",
    "replication", "sharding", "partitioning",
    "event sourcing", "cqrs", "saga",
    "kafka", "rabbitmq", "pulsar", "nats", "activemq", "zeromq",
    "grpc", "thrift", "protobuf", "avro", "flatbuffers",
    "zookeeper", "etcd", "consul",
    "microservices", "service mesh", "monolith",
    # ── Data Engineering / Analytics ──────────────────────────────────────────────
    "data engineering", "data pipeline", "etl", "elt",
    "spark", "flink", "beam", "storm", "samza",
    "airflow", "prefect", "dagster", "luigi",
    "dbt", "dbt cloud",
    "hadoop", "hdfs", "hive", "pig",
    "delta lake", "apache iceberg", "apache hudi",
    "pandas", "polars", "dask", "modin",
    "numpy", "scipy", "statsmodels",
    "tableau", "looker", "power bi", "superset", "metabase",
    "data warehouse", "data lake", "data lakehouse", "data mesh",
    "feature store", "feature engineering",
    # ── Machine Learning / AI ─────────────────────────────────────────────────────
    "machine learning", "deep learning", "reinforcement learning",
    "supervised learning", "unsupervised learning", "self-supervised",
    "neural network", "transformer", "attention", "bert", "gpt",
    "llm", "large language model", "nlp", "natural language processing",
    "computer vision", "image segmentation", "object detection",
    "generative ai", "diffusion", "gan", "vae",
    "pytorch", "tensorflow", "jax", "keras", "mxnet", "paddle",
    "hugging face", "transformers", "diffusers", "langchain", "llamaindex",
    "scikit-learn", "xgboost", "lightgbm", "catboost",
    "onnx", "tensorrt", "openvino", "tflite",
    "cuda", "cudnn", "triton", "rocm", "opencl", "metal",
    "mlflow", "wandb", "neptune", "clearml",
    "kubeflow", "sagemaker", "vertex ai", "azure ml",
    "rag", "vector database", "pinecone", "weaviate", "qdrant", "chroma",
    "embedding", "fine-tuning", "rlhf", "peft", "lora",
    "speech recognition", "tts", "asr", "whisper",
    "recommendation system", "collaborative filtering",
    "time series", "anomaly detection", "forecasting",
    # ── Computer Graphics / Simulation ────────────────────────────────────────────
    "graphics", "opengl", "vulkan", "directx", "metal", "webgpu",
    "rendering", "ray tracing", "rasterization", "shader",
    "unreal engine", "unity", "godot", "bevy",
    "simulation", "physics engine", "rigid body", "fluid simulation",
    "blender", "maya", "houdini", "3ds max",
    "3d", "point cloud", "mesh", "voxel",
    "ar", "vr", "xr", "mixed reality", "spatial computing",
    # ── Robotics ─────────────────────────────────────────────────────────────────
    "robotics", "ros", "ros2",
    "slam", "path planning", "motion planning", "trajectory optimization",
    "kinematics", "dynamics", "control theory",
    "pid", "lqr", "mpc", "kalman filter",
    "sensor fusion", "lidar", "radar", "imu", "gnss", "gps",
    "autonomous", "self-driving", "drones", "uav", "uav",
    "manipulation", "grasping", "haptics",
    # ── Embedded / Firmware ───────────────────────────────────────────────────────
    "embedded", "firmware", "bare metal", "bootloader", "bsp",
    "arm", "arm cortex", "risc-v", "mips", "avr", "pic", "stm32",
    "esp32", "esp8266", "arduino", "raspberry pi",
    "hal", "peripheral", "gpio", "uart", "spi", "i2c", "can",
    "dma", "interrupt", "watchdog", "jtag", "openocd", "segger",
    "cmsis", "zephyr", "freertos", "threadx",
    # ── FPGA / Digital Design ─────────────────────────────────────────────────────
    "fpga", "asic", "rtl", "hdl",
    "verilog", "vhdl", "systemverilog", "chisel", "spinalhdl",
    "vivado", "quartus", "synopsys", "cadence", "mentor",
    "synthesis", "place and route", "timing closure", "sta",
    "dft", "scan chain", "bist",
    "axi", "ahb", "apb", "wishbone", "avalon",
    "ddr", "ddr4", "ddr5", "lpddr", "hbm",
    "pcie", "usb", "ethernet mac", "serdes", "phy",
    "noc", "cache coherence", "tilelink",
    # ── Analog / Mixed-Signal ─────────────────────────────────────────────────────
    "analog", "mixed-signal", "adc", "dac",
    "opamp", "amplifier", "comparator", "oscillator",
    "pll", "ldo", "dcdc", "buck", "boost", "flyback",
    "filter", "rc filter", "lc filter",
    "noise", "snr", "thd", "bandwidth", "gain",
    "cadence virtuoso", "spectre", "hspice", "ltspice",
    # ── RF / Wireless ─────────────────────────────────────────────────────────────
    "rf", "radio frequency", "microwave", "millimeter wave", "mmwave",
    "antenna", "phased array", "beamforming",
    "modulation", "demodulation", "qam", "ofdm", "fsk", "psk",
    "5g", "4g", "lte", "nr", "gnb", "ue",
    "wifi", "802.11", "bluetooth", "ble", "zigbee",
    "spectrum", "signal processing", "dsp",
    "fft", "fir", "iir", "convolution",
    "link budget", "path loss", "propagation",
    "radar", "lidar", "sonar",
    "gnss", "gps", "glonass", "galileo",
    # ── Power Electronics ─────────────────────────────────────────────────────────
    "power electronics", "power systems", "power management",
    "inverter", "converter", "rectifier", "pwm",
    "mosfet", "igbt", "gan", "sic",
    "battery", "bms", "energy storage", "charging",
    "grid", "microgrid", "power grid",
    "motor drive", "motor control", "bldc", "pmsm", "foc",
    # ── PCB / Hardware Design ─────────────────────────────────────────────────────
    "pcb", "schematic", "layout", "gerber",
    "altium", "kicad", "eagle", "cadence allegro", "mentor pads",
    "signal integrity", "si", "pi", "power integrity",
    "emc", "emi", "esd",
    "bga", "qfn", "smt", "through-hole",
    "oscilloscope", "logic analyzer", "spectrum analyzer",
    "multimeter", "soldering",
    # ── Semiconductor / VLSI ──────────────────────────────────────────────────────
    "vlsi", "ic design", "chip design", "tapeout",
    "cmos", "finfet", "gaafet", "soi",
    "process node", "7nm", "5nm", "3nm",
    "lef", "def", "gds", "oasis",
    "floorplan", "placement", "routing",
    "power analysis", "ir drop", "electromigration",
    "library characterization", "cell library",
    "semiconductor", "wafer", "fab", "foundry", "tsmc", "intel foundry",
    # ── Test & Measurement / Reliability ─────────────────────────────────────────
    "ate", "test bench", "unit test", "integration test",
    "verification", "validation", "v&v",
    "uvm", "svunit", "cocotb",
    "dvt", "evt", "pvt", "fmea", "dfmea",
    "reliability", "mtbf", "qualification",
    "lab", "prototype", "bring-up",
    # Process / Chemical Engineering
    "chemical engineering", "chemical engineer", "chemistry", "chemist",
    "process engineering", "process engineer", "process design",
    "process development", "process optimization", "process simulation",
    "process modeling", "process control", "process safety",
    "production engineer", "manufacturing engineer", "plant engineer",
    "project engineer", "refinery", "petrochemical", "oil and gas",
    "renewable fuels", "polymer", "polymers", "catalyst", "catalysis",
    "reaction engineering", "kinetics", "thermodynamics",
    "heat transfer", "mass transfer", "fluid dynamics", "separations",
    "distillation", "filtration", "solids handling", "batch process",
    "continuous process", "pfd", "p&id", "pids", "pid",
    "pha", "hazop", "lopa", "moc", "relief systems",
    "overpressure protection", "equipment sizing", "line sizing",
    "hydraulics", "debottlenecking", "turnaround", "commissioning",
    # Chemical / laboratory tools and software
    "x-ray diffraction", "xrd", "profilometry", "ellipsometry",
    "atomic layer deposition", "ald", "sputtering", "thin films",
    "aspen plus", "aspen+", "aspen hysys", "hysys", "polymath",
    "labview", "aft fathom", "aft arrow", "bluebeam", "navisworks",
    "solidworks", "cswa", "engineer in training", "eit",
    "professional engineer", "pe exam", "pe license", "fe exam",
    "spanish", "chinese", "mandarin",
    # ── Disciplines / Roles ───────────────────────────────────────────────────────
    "backend", "frontend", "full stack", "fullstack",
    "devops", "platform engineering", "infrastructure",
    "data science", "data analyst", "ml engineer", "ai engineer",
    "software engineer", "software developer", "swe",
    "electrical engineer", "hardware engineer",
    "systems engineer", "solutions engineer",
    "compiler engineer", "kernel engineer",
    "site reliability", "sre",
    "security engineer", "cryptographer",
    "networking", "network engineer",
    "embedded engineer", "firmware engineer",
    "fpga engineer", "asic engineer", "rtl engineer",
    "analog engineer", "rf engineer", "signal integrity engineer",
    "pcb designer", "hardware designer",
    "product engineer", "process engineer", "yield engineer",
    "quantum", "quantum computing", "qubits",
]

# De-duplicate while preserving order (some terms appear in multiple categories)
_seen: set[str] = set()
_deduped: list[str] = []
for _kw in TECH_KEYWORDS:
    if _kw not in _seen:
        _seen.add(_kw)
        _deduped.append(_kw)
TECH_KEYWORDS = _deduped
del _seen, _deduped, _kw

# Pre-compile token-boundary patterns for each keyword so extraction is fast.
# Lookarounds handle symbol-ending terms like "C++", "P&ID", and "Aspen+".
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (kw, re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", re.IGNORECASE))
    for kw in TECH_KEYWORDS
]


def extract_keywords(title: str, description: str | None = None) -> list[str]:
    """Return all TECH_KEYWORDS that appear (word-boundary match) in title + description."""
    text = title + (" " + description if description else "")
    return [kw for kw, pat in _PATTERNS if pat.search(text)]
