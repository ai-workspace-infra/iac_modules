# instance/ec2/Makefile

GITOPS_ROOT ?= ../../../../gitops
CONFIG_DIR ?= $(GITOPS_ROOT)/resources/svc.plus/uat/aws

render:
	python ../../../utils/render_provider_backend.py \
		--config-dir $(CONFIG_DIR) \
		--template-dir ../../templates \
		--component-dir .. \
		--component ec2

init: render
	terraform init --upgrade

plan: init
	terraform plan

apply: init
	terraform apply -auto-approve

output:
	terraform output

destroy: init
	terraform destroy -auto-approve
