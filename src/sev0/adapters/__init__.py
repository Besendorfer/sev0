# Import all adapter modules to trigger @register_* decorators
from sev0.adapters.sources import cloudwatch as _cloudwatch  # noqa: F401
from sev0.adapters.channels import teams as _teams  # noqa: F401
from sev0.adapters.actions import jira as _jira  # noqa: F401
