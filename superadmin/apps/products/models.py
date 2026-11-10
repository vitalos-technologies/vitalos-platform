"""Product Pipeline permissions (ADR-044).

The product list itself is configuration (``registry.py``), so there is no table. Django permissions
need a model to hang from, so ``ProductAccess`` is unmanaged: it declares the permissions and nothing
else. Its migration only records the model state; no table is created.
"""

from django.db import models


class ProductAccess(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("view_product_pipeline", "Can view the Product Pipeline"),
            ("open_askbridge_superadmin", "Can see Askbridge details and open the Askbridge Superadmin"),
            ("open_answerd_superadmin", "Can see Answerd details and open the Answerd Superadmin"),
            (
                "open_workforce_superadmin",
                "Can see Vitalos Workforce details and open the Vitalos Workforce Superadmin",
            ),
            ("open_tipsignal_superadmin", "Can see TipSignal details and open the TipSignal Superadmin"),
            ("open_autofix_superadmin", "Can see Pitline details and open the Pitline Superadmin"),
            ("open_relay_superadmin", "Can see Relay details and open the Relay Superadmin"),
        ]

    def __str__(self):
        return "Product Pipeline access"
