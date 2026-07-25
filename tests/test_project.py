import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aios.kernel import AIOSKernel


class ProjectTest(unittest.TestCase):
    def test_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project'
            project.mkdir()
            (project / 'x.txt').write_text('ok')
            home = Path(temp) / 'home'
            with patch.dict(os.environ, {'AIOS_HOME': str(home)}):
                kernel = AIOSKernel()
                kernel.projects.add('demo', str(project))
                workspace = kernel.projects.create_workspace('demo')
                self.assertTrue((workspace / 'x.txt').exists())


if __name__ == '__main__':
    unittest.main()
