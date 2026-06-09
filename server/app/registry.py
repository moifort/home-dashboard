"""Domain registry — the core domain plus the optional ones the orchestrator and
the server iterate generically.

Each domain exposes the uniform slice API (enabled / init_schema / start / attach
/ status). The core (electricity / Linky consumption) is always built first; the
optional domains contribute their own fields via attach(). To drop an optional
domain, delete its package and remove it from OPTIONAL.
"""
from app import crypto, electricity, network, plants, solar, water
from app.electricity import power

# The core domain (always built first; mandatory).
CORE = electricity

# Optional domains, in render-attach order (otherwise irrelevant). `power` is a
# sub-domain of electricity but keeps its own slice API, so it is iterated here.
OPTIONAL = (solar, crypto, power, network, water, plants)
