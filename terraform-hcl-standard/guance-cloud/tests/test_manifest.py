import unittest

import helpers
from guance_manifest import validate_manifest


class ManifestTest(unittest.TestCase):
    def check_rejected(self, mutate, fragment):
        document = helpers.fixture()
        mutate(document)
        with self.assertRaises(ValueError) as caught:
            validate_manifest(document)
        self.assertIn(fragment, str(caught.exception))

    def test_fixture_is_valid(self):
        validate_manifest(helpers.fixture())

    def test_prod_is_rejected(self):
        self.check_rejected(lambda d: d["global"].update(environment="prod"), "UAT only")

    def test_credential_keys_are_rejected(self):
        self.check_rejected(lambda d: d["notify_objects"][0].update(opt_set="{}"), "credential-like keys")
        self.check_rejected(lambda d: d["global"].update(access_token="x"), "credential-like keys")

    def test_credential_shaped_values_are_rejected(self):
        self.check_rejected(
            lambda d: d["alert_policies"][0].update(description="https://hooks.slack" + ".com/services/T0/B0/xyz"),
            "credential-shaped",
        )

    def test_unknown_references_and_duplicate_ids(self):
        self.check_rejected(lambda d: d["monitors"][0].update(alert_policies=["nope"]), "unknown id")
        self.check_rejected(lambda d: d["alert_policies"][0]["routes"][0].update(notify_objects=["nope"]), "unknown id")
        self.check_rejected(lambda d: d["mutes"][0].update(id="uat_default"), "unique across kinds")

    def test_notify_type_allowlist(self):
        self.check_rejected(lambda d: d["notify_objects"][0].update(type="carrierPigeon"), "notify_object type")

    def test_route_status_allowlist(self):
        self.check_rejected(lambda d: d["alert_policies"][0]["routes"][0].update(status="critical,loud"), "route status")

    def test_mute_must_be_scoped_and_time_boxed(self):
        self.check_rejected(lambda d: d["mutes"][0].update(tags={}), "unscoped")
        self.check_rejected(lambda d: d["mutes"][0].update(end="2026/10/20 09:00:00"), "after start")
        self.check_rejected(lambda d: d["mutes"][0].update(end="2026/10/21 10:00:00"), "must not exceed")
        self.check_rejected(lambda d: d["mutes"][0].update(start="soon"), "YYYY/MM/DD")
        self.check_rejected(lambda d: d["mutes"][0].update(repeat="daily"), "unexpected")

    def test_measured_baseline_needs_evidence_and_no_placeholders(self):
        self.check_rejected(lambda d: d["monitors"][0].update(baseline={"status": "measured"}), "missing")
        measured = {"status": "measured", "measured_at": "2026-10-19", "window": "7d", "source": "uat", "summary": "p95=300ms"}
        self.check_rejected(lambda d: d["monitors"][0].update(baseline=measured), "placeholders")


if __name__ == "__main__":
    unittest.main()
