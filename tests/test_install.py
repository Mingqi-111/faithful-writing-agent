import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native_install', Path(__file__).resolve().parents[1] / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def test_each_project_path_and_no_user_data_copy(self):
        for host, location in installer.LOCATIONS.items():
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / 'faithful-writing-agent'
                source.mkdir()
                (source / 'SKILL.md').write_text('test')
                (source / '.faithful-writing-agent').mkdir()
                (source / '.faithful-writing-agent/private.txt').write_text('private')
                project = root / 'writing-project'
                project.mkdir()
                with patch.object(installer, 'ROOT', source):
                    result = installer.install(host, project)
                    self.assertEqual(Path(result['path']), (project / location / source.name).resolve())
                    self.assertTrue((Path(result['path']) / 'SKILL.md').exists())
                    self.assertFalse((Path(result['path']) / '.faithful-writing-agent').exists())
                    with self.assertRaises(ValueError):
                        installer.install(host, project)

    def test_cannot_install_recursively_into_skill(self):
        with self.assertRaises(ValueError):
            installer.install('codex', installer.ROOT)

    def test_github_archive_directory_uses_canonical_skill_name(self):
        for host, location in installer.LOCATIONS.items():
            with self.subTest(host=host), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / 'faithful-writing-agent-main'
                source.mkdir()
                (source / 'SKILL.md').write_text('name: faithful-writing-agent')
                project = root / 'writing-project'
                project.mkdir()
                with patch.object(installer, 'ROOT', source):
                    result = installer.install(host, project)
                destination = project / location / 'faithful-writing-agent'
                self.assertEqual(Path(result['path']), destination.resolve())
                self.assertEqual((destination / 'SKILL.md').read_text(), 'name: faithful-writing-agent')
                self.assertFalse((project / location / source.name).exists())


if __name__ == '__main__':
    unittest.main()
