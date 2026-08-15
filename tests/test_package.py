import unittest

import lisjong_engine


class PackageImportTest(unittest.TestCase):
    def test_package_imports(self) -> None:
        self.assertIsNotNone(lisjong_engine)


if __name__ == "__main__":
    unittest.main()
