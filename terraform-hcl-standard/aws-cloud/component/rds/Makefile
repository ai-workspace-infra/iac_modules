SHELL := /bin/bash

TF=terraform

GITOPS_ROOT ?= ../../../../gitops
CONFIG_DIR ?= $(GITOPS_ROOT)/resources/svc.plus/uat/aws

render:
	python ../../../utils/render_provider_backend.py \
		--config-dir $(CONFIG_DIR) \
		--template-dir ../../templates \
		--component-dir .. \
		--component rds

init:
	$(TF) init --upgrade

plan:
	$(TF) plan

apply:
	$(TF) apply -auto-approve

output:
	$(TF) output

destroy:
	$(TF) destroy -auto-approve
