import os
import tempfile
import unittest
from unittest.mock import patch

from aios.kernel import AIOSKernel


class MemoryTest(unittest.TestCase):
    def test_failure_memory(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'AIOS_HOME': temp}):
            kernel = AIOSKernel()
            kernel.memory.record_failure('same bug', project='demo', verified=True)
            self.assertEqual(len(kernel.memory.find_failures('same bug', 'demo')), 1)


if __name__ == '__main__':
    unittest.main()
