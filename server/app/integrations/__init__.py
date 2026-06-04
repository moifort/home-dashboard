"""Data integrations (Linky, EcoFlow, Cumulus, Crypto).

Linky is the core (mandatory) slice. The optional slices conform to a uniform
interface — enabled(), init_schema(), start(), attach(data), status() — so the
orchestrator and server can iterate them generically. To drop an integration,
delete its package and remove it from OPTIONAL below.
"""
from app import crypto
from app.integrations import ecoflow, power, unifi, water

# Order defines the render-attach order and is otherwise irrelevant.
OPTIONAL = (ecoflow, crypto, power, unifi, water)
