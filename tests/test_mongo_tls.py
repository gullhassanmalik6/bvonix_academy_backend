"""MongoDB TLS stays verified unless development explicitly opts out."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.db.mongo_tls import mongo_client_options, tls_allow_invalid_certificates, uri_uses_tls


ATLAS = "mongodb+srv://user:secret@cluster.example.net/bvonix?retryWrites=true"
ATLAS_INSECURE = ATLAS + "&tlsAllowInvalidCertificates=true"
LOCAL = "mongodb://127.0.0.1:27017"


class MongoTlsPolicyTests(unittest.TestCase):
    def test_production_validates_certificates(self) -> None:
        self.assertFalse(
            tls_allow_invalid_certificates(
                app_env="production",
                allow_invalid_certificates=False,
                uri=ATLAS,
            )
        )
        options = mongo_client_options(
            SimpleNamespace(
                app_env="production",
                mongodb_tls_allow_invalid_certificates=False,
                mongodb_uri=ATLAS,
            )
        )
        self.assertFalse(options["tlsAllowInvalidCertificates"])

    def test_production_refuses_an_invalid_certificate_flag(self) -> None:
        with self.assertRaises(ValueError):
            tls_allow_invalid_certificates(
                app_env="production",
                allow_invalid_certificates=True,
                uri=ATLAS,
            )

    def test_production_refuses_insecure_options_in_the_uri(self) -> None:
        for uri in (
            ATLAS_INSECURE,
            ATLAS + "&tlsAllowInvalidHostnames=true",
            ATLAS + "&tlsInsecure=true",
            "mongodb://db.example.net:27017/?tls=true&tlsAllowInvalidCertificates=true",
        ):
            with self.subTest(uri=uri.split("?", 1)[-1]):
                with self.assertRaises(ValueError):
                    tls_allow_invalid_certificates(
                        app_env="Production",
                        allow_invalid_certificates=False,
                        uri=uri,
                    )

    def test_uri_flag_alone_does_not_disable_validation_in_development(self) -> None:
        self.assertFalse(
            tls_allow_invalid_certificates(
                app_env="development",
                allow_invalid_certificates=False,
                uri=ATLAS_INSECURE,
            )
        )

    def test_development_bypass_requires_the_explicit_flag(self) -> None:
        self.assertTrue(
            tls_allow_invalid_certificates(
                app_env="development",
                allow_invalid_certificates=True,
                uri=ATLAS,
            )
        )
        options = mongo_client_options(
            SimpleNamespace(
                app_env="development",
                mongodb_tls_allow_invalid_certificates=True,
                mongodb_uri=ATLAS,
            )
        )
        self.assertTrue(options["tlsAllowInvalidCertificates"])

    def test_non_development_environment_cannot_opt_out(self) -> None:
        with self.assertRaises(ValueError):
            tls_allow_invalid_certificates(
                app_env="staging",
                allow_invalid_certificates=True,
                uri=LOCAL,
            )

    def test_local_connection_without_tls_is_unchanged(self) -> None:
        self.assertFalse(uri_uses_tls(LOCAL))
        options = mongo_client_options(
            SimpleNamespace(
                app_env="development",
                mongodb_tls_allow_invalid_certificates=False,
                mongodb_uri=LOCAL,
            )
        )
        self.assertNotIn("tlsAllowInvalidCertificates", options)


if __name__ == "__main__":
    unittest.main()
