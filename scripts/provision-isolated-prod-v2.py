#!/usr/bin/env python3
"""Create only the explicitly declared, isolated PROD V2 resources.

No SSH, host configuration, database operation or DNS cutover is performed.
CMDB output contains runtime facts and stays outside GitOps.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import yaml


def gcloud(*args):
    result = subprocess.run(["gcloud", *args], text=True, capture_output=True)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def exists(*args):
    return subprocess.run(["gcloud", *args], text=True, capture_output=True).returncode == 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--ssh-cidr", required=True)
    p.add_argument("--cmdb", required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    spec = yaml.safe_load(pathlib.Path(a.manifest).read_text())["spec"]
    assert spec["project_id"] == "open-platform-prod"
    assert spec["existing_production_mutation"] is False
    assert spec["dns_cutover"] is False
    names = [i["name"] for i in spec["instances"]]
    assert len(names) == 4 and len(set(names)) == 4
    assert all(n.endswith("-prod-v2") for n in names)
    assert spec["network"] == spec["subnet"] == "web-saas-prod-v2"
    assert spec["subnet_cidr"] == "10.74.0.0/24"
    common = ["--project=" + spec["project_id"], "--quiet"]
    zone = "--zone=" + spec["zone"]
    region = "--region=" + spec["region"]
    policy = json.loads(gcloud("resource-manager", "org-policies", "describe", "compute.vmExternalIpAccess", "--effective", "--format=json", *common))
    current = policy.get("listPolicy", {}).get("allowedValues", [])
    assert current and not policy.get("listPolicy", {}).get("deniedValues")
    additions = [f"projects/{spec['project_id']}/zones/{spec['zone']}/instances/{n}" for n in names]
    print("Plan: create isolated network/subnet, four static addresses/VMs, one data disk; append four public-IP allowances; no deletion/replacement/DNS mutation.")
    if not a.apply:
        return
    # Preserve every current effective allow entry. Never relax to allow-all.
    desired = {"constraint": "constraints/compute.vmExternalIpAccess", "listPolicy": {"allowedValues": sorted(set(current + additions))}}
    direct = subprocess.run(["gcloud", "resource-manager", "org-policies", "describe", "compute.vmExternalIpAccess", "--format=json", *common], text=True, capture_output=True)
    if direct.returncode == 0:
        etag = json.loads(direct.stdout).get("etag")
        if etag:
            desired["etag"] = etag
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as f:
        yaml.safe_dump(desired, f)
        f.flush()
        gcloud("resource-manager", "org-policies", "set-policy", f.name, *common)
    if not exists("compute", "networks", "describe", spec["network"], *common):
        gcloud("compute", "networks", "create", spec["network"], "--subnet-mode=custom", *common)
    if not exists("compute", "networks", "subnets", "describe", spec["subnet"], region, *common):
        gcloud("compute", "networks", "subnets", "create", spec["subnet"], region, "--network=" + spec["network"], "--range=" + spec["subnet_cidr"], *common)
    rules = [
        ("ssh", "tcp:22", a.ssh_cidr + ",35.235.240.0/20"),
        ("https", "tcp:80,tcp:443,udp:443", "0.0.0.0/0"),
        ("private-db", "tcp:15433", spec["subnet_cidr"]),
    ]
    for suffix, allow, source in rules:
        name = "web-saas-prod-v2-" + suffix
        if not exists("compute", "firewall-rules", "describe", name, *common):
            gcloud("compute", "firewall-rules", "create", name, "--network=" + spec["network"], "--target-tags=prod-v2", "--allow=" + allow, "--source-ranges=" + source, *common)
    records = []
    for item in spec["instances"]:
        name = item["name"]
        address_name = name + "-ip"
        if not exists("compute", "addresses", "describe", address_name, region, *common):
            gcloud("compute", "addresses", "create", address_name, region, *common)
        ip = gcloud("compute", "addresses", "describe", address_name, region, "--format=value(address)", *common).strip()
        if not exists("compute", "instances", "describe", name, zone, *common):
            gcloud("compute", "instances", "create", name, zone, "--machine-type=" + item["machine_type"], "--subnet=" + spec["subnet"], "--address=" + ip, "--image-family=debian-12", "--image-project=debian-cloud", "--boot-disk-size=" + str(item["boot_disk_gb"]), "--boot-disk-type=pd-balanced", "--metadata=enable-oslogin=TRUE", "--no-service-account", "--no-scopes", "--tags=prod-v2", "--labels=environment=prod,stack=prod-v2,role=" + item["role"], "--deletion-protection", *common)
        if item.get("data_disk_gb"):
            disk = name + "-data"
            if not exists("compute", "disks", "describe", disk, zone, *common):
                gcloud("compute", "disks", "create", disk, zone, "--size=" + str(item["data_disk_gb"]), "--type=pd-balanced", *common)
            instance = json.loads(gcloud("compute", "instances", "describe", name, zone, "--format=json", *common))
            if not any(d.get("deviceName") == disk for d in instance["disks"]):
                gcloud("compute", "instances", "attach-disk", name, zone, "--disk=" + disk, "--device-name=" + disk, *common)
        instance = json.loads(gcloud("compute", "instances", "describe", name, zone, "--format=json", *common))
        nic = instance["networkInterfaces"][0]
        records.append({"name": name, "role": item["role"], "project": spec["project_id"], "zone": spec["zone"], "ip": nic["accessConfigs"][0]["natIP"], "private_ip": nic["networkIP"]})
        print(name, instance["status"], records[-1]["ip"])
    dest = pathlib.Path(a.cmdb)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump({"instances": records}))
    dest.chmod(0o600)


if __name__ == "__main__":
    main()
