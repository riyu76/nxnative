"""Package the real compile-fixture IPA wrapper with synthetic inputs; no Xcode or copyrighted data."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('build_smoke_fixture', REPO / 'dm/ios/tools/build_smoke.py')
assert spec and spec.loader
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class CompileFixture(unittest.TestCase):
    def test_ipa_structure_and_nonplayable_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / 'DmIOS.app'
            app.mkdir()
            (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'DmIOS'}))
            (app / 'DmIOS').write_bytes(b'Synthetic test executable; no Nintendo code.\n')
            ipa = root / 'fixture.ipa'
            smoke.package_fixture(app, ipa)
            with zipfile.ZipFile(ipa) as z:
                self.assertIsNone(z.testzip())
                files = {n for n in z.namelist() if not n.endswith('/')}
                self.assertEqual(files, {'Payload/DmIOS.app/Info.plist', 'Payload/DmIOS.app/DmIOS', 'Payload/DmIOS.app/dm/env.txt'})
                info = plistlib.loads(z.read('Payload/DmIOS.app/Info.plist'))
                self.assertTrue(info['DMCiCompileFixture'])
                self.assertEqual(z.read('Payload/DmIOS.app/dm/env.txt'), b'DM_GPU_COMPAT=1\n')


if __name__ == '__main__':
    unittest.main()
