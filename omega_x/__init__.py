"""OMEGA-X executable, deterministic user-space model (not physical silicon)."""
__version__ = "6.0.0"
from .model import Workload, Profile, load_profile, Domain, Instruction
from .runtime import OmegaRuntime
