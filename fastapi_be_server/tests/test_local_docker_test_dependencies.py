import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalDockerTestDependenciesContractTest(unittest.TestCase):
    def test_local_api_installs_persisted_test_dependency_group(self):
        pyproject = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        test_group = pyproject["tool"]["poetry"]["group"]["test"]
        self.assertIs(test_group["optional"], True)
        test_dependencies = test_group["dependencies"]

        self.assertEqual(test_dependencies["pytest"], "9.1.1")
        self.assertEqual(test_dependencies["pytest-asyncio"], "1.4.0")

        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG POETRY_INSTALL_GROUPS=main", dockerfile)
        self.assertIn('poetry install --only="$POETRY_INSTALL_GROUPS"', dockerfile)

        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('POETRY_INSTALL_GROUPS: "main,test"', compose)


if __name__ == "__main__":
    unittest.main()
