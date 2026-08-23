"""Build-only import and supply-chain verification."""
from importlib.metadata import version

import boto3
import demucs
import runpod

from contract import (
    ACE_STEP_MODEL_REVISION,
    DEMUCS_CHECKPOINT_SHA256,
)

assert ACE_STEP_MODEL_REVISION == "e432212fec32b8965a14ffa57ae653438d6abd14"
assert DEMUCS_CHECKPOINT_SHA256 == (
    "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
)
assert boto3.__version__ == "1.43.72"
assert version("demucs") == "4.0.1"
assert version("runpod") == "1.11.0"
assert demucs is not None and runpod is not None
