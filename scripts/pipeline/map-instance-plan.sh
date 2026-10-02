#!/bin/bash
PLAN="${INPUT_INSTANCE_PLAN:-${INPUT_INSTANCE_PLAN_____4C8G_:-}}"
PROVIDER="${INPUT_CLOUD_PROVIDER:-vultr-vps}"
AGENT_PROXY_PLAN="${INPUT_AGENT_PROXY_PLAN:-2C1G}"

case "${PLAN}" in
  1C2G|2C2G|2C4G|2C8G|4C8G) ;;
  *)
    echo "::error::Unsupported instance_plan='${PLAN}'. Expected 1C2G, 2C2G, 2C4G, 2C8G, or 4C8G." >&2
    exit 1
    ;;
esac

case "${AGENT_PROXY_PLAN}" in
  1C1G|1C2G|2C1G|2C2G) ;;
  *)
    echo "::error::Unsupported agent_proxy_plan='${AGENT_PROXY_PLAN}'. Expected 1C1G, 1C2G, 2C1G, or 2C2G." >&2
    exit 1
    ;;
esac

if [ "$PROVIDER" == "aws-cloud" ]; then
  if [ "$PLAN" == "1C2G" ]; then
    echo "api=t4g.small" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C2G" ]; then
    echo "api=t4g.small" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C4G" ]; then
    echo "api=t4g.medium" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C8G" ]; then
    echo "api=t4g.large" >> "$GITHUB_OUTPUT"
  else
    echo "api=t4g.large" >> "$GITHUB_OUTPUT"
  fi
elif [ "$PROVIDER" == "akamai-cloud" ]; then
  # Akamai's high-memory 2-vCPU plan is 48 GiB, not the requested 2C8G
  # shape.  Use the current G8 Dedicated 8x2 plan for an exact 2 vCPU/8 GiB
  # mapping.  Keep this explicit so a generation rename cannot silently
  # oversize AI Workspace nodes again.
  if [ "$PLAN" == "1C2G" ]; then
    echo "api=g6-standard-1" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C2G" ]; then
    # Akamai/Linode has no exact 2 vCPU/2 GiB general-purpose type; keep the
    # logical matrix profile valid and use the smallest 2-vCPU standard type
    # so the plan exposes the provider-side size difference for approval.
    echo "api=g6-standard-2" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C4G" ]; then
    echo "api=g6-standard-2" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C8G" ]; then
    echo "api=g8-dedicated-8-2" >> "$GITHUB_OUTPUT"
  else
    echo "api=g6-standard-4" >> "$GITHUB_OUTPUT"
  fi
else
  # 默认 vultr-vps
  if [ "$PLAN" == "1C2G" ]; then
    echo "api=vc2-1c-2gb" >> "$GITHUB_OUTPUT"
  elif [ "$PLAN" == "2C4G" ]; then
    echo "api=vc2-2c-4gb" >> "$GITHUB_OUTPUT"
  else
    echo "api=vc2-4c-8gb" >> "$GITHUB_OUTPUT"
  fi
fi

if [ "$PROVIDER" == "aws-cloud" ]; then
  if [ "$AGENT_PROXY_PLAN" == "1C1G" ] || [ "$AGENT_PROXY_PLAN" == "2C1G" ]; then
    echo "agent_api=t4g.micro" >> "$GITHUB_OUTPUT"
  elif [ "$AGENT_PROXY_PLAN" == "1C2G" ]; then
    echo "agent_api=t4g.small" >> "$GITHUB_OUTPUT"
  else
    echo "agent_api=t4g.small" >> "$GITHUB_OUTPUT"
  fi
elif [ "$PROVIDER" == "akamai-cloud" ]; then
  if [ "$AGENT_PROXY_PLAN" == "1C1G" ] || [ "$AGENT_PROXY_PLAN" == "1C2G" ]; then
    echo "agent_api=g6-standard-1" >> "$GITHUB_OUTPUT"
  else
    echo "agent_api=g6-standard-2" >> "$GITHUB_OUTPUT"
  fi
else
  if [ "$AGENT_PROXY_PLAN" == "1C1G" ]; then
    echo "agent_api=vc2-1c-1gb" >> "$GITHUB_OUTPUT"
  elif [ "$AGENT_PROXY_PLAN" == "1C2G" ]; then
    echo "agent_api=vc2-1c-2gb" >> "$GITHUB_OUTPUT"
  else
    echo "agent_api=vc2-2c-2gb" >> "$GITHUB_OUTPUT"
  fi
fi
