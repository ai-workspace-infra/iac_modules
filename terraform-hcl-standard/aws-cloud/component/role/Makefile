SHELL := /bin/bash

TF=terraform

CONFIG_FILES ?=
GITOPS_ROOT ?= ../../../../gitops
CONFIG_DIR ?= $(GITOPS_ROOT)/resources/svc.plus/uat/aws

CONFIG_FILES_JSON := $(shell python - <<'PY'
import json
from pathlib import Path

raw = '''$(CONFIG_FILES)'''
files = [line.strip() for line in raw.splitlines() if line.strip()]
resolved = [str(Path(path).expanduser().resolve()) for path in files]
print(json.dumps(resolved)) if resolved else print("")
PY)

CONFIG_FILES_ENV := $(if $(CONFIG_FILES_JSON),TF_VAR_config_files='$(CONFIG_FILES_JSON)')

render:
	python ../../../utils/render_provider_backend.py \
		--config-dir $(CONFIG_DIR) \
		--template-dir ../../templates \
		--component-dir .. \
		--component role

init:
        $(CONFIG_FILES_ENV) $(TF) init --upgrade

plan:
        $(CONFIG_FILES_ENV) $(TF) plan

apply:
        $(CONFIG_FILES_ENV) $(TF) apply -auto-approve

destroy:
        $(CONFIG_FILES_ENV) $(TF) destroy -auto-approve
