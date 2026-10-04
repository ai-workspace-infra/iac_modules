mock_provider "aws" {
  override_data {
    target = data.aws_vpc.uat
    values = {
      id = "vpc-0123456789abcdef0"
    }
  }
}

variables {
  run_id                    = "xcl-123-1"
  expires_at                = "2026-09-08T12:00:00Z"
  runner_cidr               = "198.51.100.10/32"
  ssh_public_key            = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample desktop-test"
  aws_region                = "us-east-1"
  aws_client_instance_type  = "t4g.micro"
  aws_gateway_instance_type = "t4g.small"
  aws_ami                   = "ami-0123456789abcdef0"
  zero_accounts_api_url     = "https://accounts.example.test"
  zero_portal_url           = "https://portal.example.test"
}

run "instances_have_absolute_expiry_lifecycle" {
  command = plan

  assert {
    condition     = aws_instance.gateway.instance_type == "t4g.small"
    error_message = "Gateway must remain t4g.small."
  }
  assert {
    condition     = aws_instance.client.instance_type == "t4g.micro"
    error_message = "One must remain t4g.micro."
  }
  assert {
    condition = alltrue([
      strcontains(aws_instance.gateway.user_data, "2026-09-08T12:00:00Z"),
      strcontains(aws_instance.client.user_data, "2026-09-08T12:00:00Z"),
      strcontains(aws_instance.gateway.user_data, "OnCalendar=$${expiry_calendar}"),
      strcontains(aws_instance.gateway.user_data, "Persistent=true"),
      strcontains(aws_instance.gateway.user_data, "ExecStart=/sbin/poweroff"),
      strcontains(aws_instance.client.user_data, "OnCalendar=$${expiry_calendar}"),
      strcontains(aws_instance.client.user_data, "Persistent=true"),
      strcontains(aws_instance.client.user_data, "ExecStart=/sbin/poweroff"),
    ])
    error_message = "Both user_data scripts must carry the absolute expiry timer."
  }
}

run "invalid_calendar_expiry_is_invalid" {
  command = plan
  variables {
    expires_at = "2026-02-30T12:00:00Z"
  }
  expect_failures = [var.expires_at]
}

run "shell_metacharacters_in_expiry_are_invalid" {
  command = plan
  variables {
    expires_at = "2026-09-08T12:00:00Z';touch /tmp/xconnect-lab-pwned;echo '"
  }
  expect_failures = [var.expires_at]
}

run "empty_list_is_valid" {
  command = plan
  variables {
    desktop_ingress_cidrs = []
  }
}

run "one_canonical_ipv4_32_is_valid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.42/32"]
  }
}

run "two_canonical_ipv4_32s_are_valid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.42/32", "203.0.113.7/32"]
  }
}

run "zero_network_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "non_host_network_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.0/24"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "ipv6_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["2001:db8::1/32"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "leading_space_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = [" 198.51.100.42/32"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "trailing_space_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.42/32 "]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "duplicate_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.42/32", "198.51.100.42/32"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "three_items_are_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["198.51.100.42/32", "203.0.113.7/32", "192.0.2.9/32"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "invalid_string_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = ["not-a-cidr"]
  }
  expect_failures = [var.desktop_ingress_cidrs]
}

run "null_is_invalid" {
  command = plan
  variables {
    desktop_ingress_cidrs = null
  }
  expect_failures = [var.desktop_ingress_cidrs]
}
